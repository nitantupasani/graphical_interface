from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

import dash
from dash import Dash, Input, Output, State, callback, dcc, html
import dash_cytoscape as cyto


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class NodeType:
    key: str
    label: str
    color: str


NODE_TYPES: List[NodeType] = [
    NodeType("building", "Building", "#38bdf8"),
    NodeType("hot-water", "Hot Water Loop", "#f97316"),
    NodeType("cold-water", "Cold Water Loop", "#60a5fa"),
    NodeType("heating-curve", "Heating Curve", "#facc15"),
    NodeType("sensors", "Sensors", "#a855f7"),
    NodeType("ahu", "Air Handling Units", "#22c55e"),
    NodeType("zone", "Zones", "#f472b6"),
]

TYPE_MAP: Dict[str, NodeType] = {node_type.key: node_type for node_type in NODE_TYPES}


def make_node(
    node_id: str,
    label: str,
    type_key: str,
    parent: Optional[str] = None,
    position: Optional[Dict[str, float]] = None,
) -> Dict:
    type_label = TYPE_MAP[type_key].label
    combined_label = f"{type_label}\n{label}"
    data = {
        "id": node_id,
        "label": combined_label,
        "customLabel": label,
        "type": type_key,
        "typeLabel": type_label,
        "color": TYPE_MAP[type_key].color,
    }
    if parent:
        data["parent"] = parent
    node = {"data": data, "classes": type_key}
    if position:
        node["position"] = position
    return node


def make_edge(source: str, target: str) -> Dict:
    edge_id = f"edge-{source}-{target}"
    return {"data": {"id": edge_id, "source": source, "target": target}}


def build_children_map(elements: List[Dict]) -> Dict[str, List[str]]:
    children_map: Dict[str, List[str]] = {}
    for element in elements:
        data = element.get("data", {})
        if "parent" in data:
            children_map.setdefault(data["parent"], []).append(data["id"])
    return children_map


def collect_descendants(root_id: str, children_map: Dict[str, List[str]]) -> Set[str]:
    hidden: Set[str] = set()
    queue = list(children_map.get(root_id, []))
    while queue:
        current = queue.pop(0)
        hidden.add(current)
        queue.extend(children_map.get(current, []))
    return hidden


def apply_visibility(elements: List[Dict], collapsed: Set[str]) -> List[Dict]:
    children_map = build_children_map(elements)
    hidden: Set[str] = set()
    for collapsed_id in collapsed:
        hidden.update(collect_descendants(collapsed_id, children_map))

    visible_elements: List[Dict] = []
    hidden_nodes = hidden
    for element in elements:
        data = element.get("data", {})
        element_id = data.get("id")
        source = data.get("source")
        target = data.get("target")
        is_edge = source is not None and target is not None
        element_hidden = False
        if is_edge:
            element_hidden = source in hidden_nodes or target in hidden_nodes
        else:
            element_hidden = element_id in hidden_nodes
        base_classes = element.get("classes", "")
        if element_hidden:
            element = {**element, "classes": f"hidden {base_classes}".strip()}
        else:
            element = {**element, "classes": base_classes}
        visible_elements.append(element)
    return visible_elements


def default_stylesheet() -> List[Dict]:
    stylesheet = [
        {
            "selector": "node",
            "style": {
                "shape": "round-rectangle",
                "background-color": "data(color)",
                "label": "data(label)",
                "color": "#f8fafc",
                "text-valign": "center",
                "text-halign": "center",
                "text-wrap": "wrap",
                "text-max-width": "100px",
                "text-outline-color": "#0f172a",
                "text-outline-width": 2,
                "font-size": 11,
                "width": 110,
                "height": 70,
                "padding": 8,
                "border-radius": 12,
            },
        },
        {
            "selector": "node.building",
            "style": {
                "width": 150,
                "height": 100,
                "font-size": 12,
                "padding": 12,
                "text-max-width": "130px",
            },
        },
        {
            "selector": "edge",
            "style": {
                "width": 3,
                "line-color": "#94a3b8",
                "curve-style": "bezier",
                "target-arrow-color": "#94a3b8",
                "target-arrow-shape": "triangle",
            },
        },
        {"selector": ".selected", "style": {"border-width": 4, "border-color": "#38bdf8"}},
        {"selector": ".hidden", "style": {"display": "none"}},
    ]
    for node_type in NODE_TYPES:
        stylesheet.append(
            {
                "selector": f'node[type = "{node_type.key}"]',
                "style": {"background-color": node_type.color},
            }
        )
    return stylesheet


def initial_elements() -> List[Dict]:
    return [
        make_node("building", "Main Building", "building"),
    ]


def legend_items() -> List[html.Li]:
    items = []
    for node_type in NODE_TYPES:
        items.append(
            html.Li(
                [
                    html.Span(style={"background": node_type.color}),
                    html.Span(node_type.label),
                ]
            )
        )
    return items


app = Dash(__name__)
app.title = "Building Systems Graph"

app.layout = html.Div(
    className="app",
    children=[
        html.Header(
            children=[
                html.Div(
                    children=[
                        html.H1("Building Systems Graph"),
                        html.P(
                            "Double-click nodes to edit labels inline. Double-click canvas to add child nodes. "
                            "Right-click or Ctrl+click nodes to change type. Enable connection mode to link nodes."
                        ),
                    ]
                ),
                html.Div(
                    className="controls",
                    children=[
                        html.Button("Fit to View", id="fit-btn", n_clicks=0),
                        html.Button("Re-layout", id="layout-btn", n_clicks=0),
                    ],
                ),
            ]
        ),
        html.Div(
            className="content",
            children=[
                html.Aside(
                    children=[
                        html.H2("Node Types"),
                        html.Ul(legend_items(), id="legend"),
                        html.Div(
                            className="panel",
                            children=[
                                html.H3("Selection"),
                                html.Div(id="selection-label", className="selection"),
                                html.Div(
                                    className="hint-text",
                                    children=[
                                        "• Single-click to select a node",
                                        html.Br(),
                                        "• Double-click to edit label",
                                        html.Br(),
                                        "• Use 'Change Type' button to assign node type",
                                    ],
                                ),
                                html.Button("Change Type", id="show-type-menu", n_clicks=0, style={"marginBottom": "0.5rem"}),
                                html.Button("Toggle Collapse", id="toggle-collapse", n_clicks=0),
                            ],
                        ),
                        html.Div(
                            className="panel",
                            children=[
                                html.H3("Connection Mode"),
                                dcc.Checklist(
                                    id="connect-mode",
                                    options=[{"label": "Enable link mode", "value": "on"}],
                                    value=[],
                                    labelStyle={"display": "flex", "alignItems": "center"},
                                ),
                            ],
                        ),
                        html.Div(
                            className="panel hint",
                            children=[
                                html.H3("Quick Tips"),
                                html.Ul(
                                    [
                                        html.Li("Double-click node to edit label inline."),
                                        html.Li("Double-click canvas to add child node."),
                                        html.Li("Right-click node to change its type."),
                                        html.Li("Enable connection mode to link nodes."),
                                        html.Li("Mouse wheel zooms, drag to pan canvas."),
                                    ]
                                ),
                            ],
                        ),
                    ]
                ),
                html.Main(
                    children=[
                        cyto.Cytoscape(
                            id="graph",
                            elements=initial_elements(),
                            layout={"name": "cose", "animate": True, "fit": True},
                            stylesheet=default_stylesheet(),
                            style={"width": "100%", "height": "100%"},
                            zoomingEnabled=True,
                            userZoomingEnabled=True,
                            userPanningEnabled=True,
                            boxSelectionEnabled=False,
                            minZoom=0.3,
                            maxZoom=3,
                            wheelSensitivity=0.1,
                        )
                    ]
                ),
            ],
        ),
        dcc.Store(id="elements-store", data=initial_elements()),
        dcc.Store(id="collapsed-store", data=[]),
        dcc.Store(id="selected-store", data="building"),
        dcc.Store(id="last-tap", data={"timestamp": 0, "node": None}),
        dcc.Store(id="context-menu-visible", data=False),
        dcc.Store(id="context-menu-pos", data={"x": 0, "y": 0}),
        dcc.Store(id="right-click-node", data=None),
        dcc.Store(id="editing-node", data=None),
        html.Div(
            id="context-menu",
            className="context-menu",
            style={"display": "none"},
            children=[
                html.H4("Node Type"),
                dcc.Dropdown(
                    id="context-type-select",
                    options=[
                        {"label": node_type.label, "value": node_type.key}
                        for node_type in NODE_TYPES
                    ],
                    value="building",
                    clearable=False,
                ),
                html.Div(
                    className="context-actions",
                    children=[
                        html.Button("Apply", id="context-apply", n_clicks=0),
                        html.Button("Cancel", id="context-cancel", n_clicks=0),
                    ],
                ),
            ],
        ),
        html.Div(
            id="edit-label-dialog",
            className="edit-dialog",
            style={"display": "none"},
            children=[
                html.H4("Edit Label"),
                dcc.Input(id="label-input", type="text", placeholder="Enter label", value=""),
                html.Div(
                    className="dialog-actions",
                    children=[
                        html.Button("Save", id="save-label", n_clicks=0),
                        html.Button("Cancel", id="cancel-label", n_clicks=0),
                    ],
                ),
            ],
        ),
    ],
)


@callback(
    Output("elements-store", "data"),
    Output("selected-store", "data", allow_duplicate=True),
    Output("last-tap", "data"),
    Output("collapsed-store", "data", allow_duplicate=True),
    Input("graph", "tapNodeData"),
    State("elements-store", "data"),
    State("selected-store", "data"),
    State("last-tap", "data"),
    State("collapsed-store", "data"),
    prevent_initial_call=True,
)
def handle_node_tap(
    tap_node_data: Optional[Dict],
    elements: List[Dict],
    selected: str,
    last_tap: Dict,
    collapsed: List[str],
) -> Tuple[List[Dict], str, Dict, List[str]]:
    if not tap_node_data:
        return elements, selected, last_tap, collapsed

    tapped_id = tap_node_data.get("id")
    timestamp = _now_ms()

    # Just update selection, double-click editing handled by show_inline_edit
    return elements, tapped_id, {"node": tapped_id, "timestamp": timestamp}, collapsed


@callback(
    Output("elements-store", "data", allow_duplicate=True),
    Output("selected-store", "data", allow_duplicate=True),
    Output("last-tap", "data", allow_duplicate=True),
    Input("graph", "tapNode"),
    State("graph", "tapNodeData"),
    State("elements-store", "data"),
    State("selected-store", "data"),
    State("last-tap", "data"),
    prevent_initial_call=True,
)
def handle_canvas_double_click(
    tap_node: Optional[Dict],
    tap_node_data: Optional[Dict],
    elements: List[Dict],
    selected: str,
    last_tap: Dict,
) -> Tuple[List[Dict], str, Dict]:
    # Only handle canvas clicks (not node clicks)
    if tap_node_data:
        # Node was clicked, not canvas
        return elements, selected, last_tap
    
    if not tap_node:
        return elements, selected, last_tap
    
    timestamp = _now_ms()
    last_canvas_timestamp = last_tap.get("canvasTimestamp", 0)
    
    # Double-click detection (within 400ms)
    if (timestamp - last_canvas_timestamp) < 400 and last_canvas_timestamp > 0:
        # Create new node as child of selected node
        position = tap_node.get("position", {"x": 0, "y": 0})
        node_id = f"node-{uuid.uuid4().hex[:6]}"
        new_node = make_node(node_id, "New Node", "sensors", parent=selected, position=position)
        updated_last_tap = {**last_tap, "canvasTimestamp": 0, "timestamp": 0}
        return elements + [new_node], node_id, updated_last_tap
    
    updated_last_tap = {**last_tap, "canvasTimestamp": timestamp}
    return elements, selected, updated_last_tap


@callback(
    Output("context-menu", "style"),
    Output("context-type-select", "value"),
    Output("right-click-node", "data"),
    Input("graph", "mouseoverNodeData"),
    Input("show-type-menu", "n_clicks"),
    State("graph", "mouseoverNodeData"),
    State("selected-store", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def show_context_menu(
    mouseover_data: Optional[Dict],
    button_clicks: int,
    current_mouseover: Optional[Dict],
    selected: str,
    elements: List[Dict],
) -> Tuple[Dict, str, Optional[str]]:
    ctx = dash.callback_context
    if not ctx.triggered:
        return {"display": "none"}, "building", None

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Get current type of selected node
    current_type = "building"
    for element in elements:
        data = element.get("data", {})
        if data.get("id") == selected:
            current_type = data.get("type", "building")
            break

    if trigger_id == "show-type-menu":
        # Show context menu centered on screen from button click
        return (
            {"display": "flex", "left": "50%", "top": "50%", "transform": "translate(-50%, -50%)"},
            current_type,
            selected,
        )

    return {"display": "none"}, current_type, None


@callback(
    Output("context-menu", "style", allow_duplicate=True),
    Output("context-type-select", "value", allow_duplicate=True),
    Output("selected-store", "data", allow_duplicate=True),
    Input("graph", "tapNodeData"),
    State("graph", "tapNode"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def handle_right_click(
    tap_node_data: Optional[Dict],
    tap_node: Optional[Dict],
    elements: List[Dict],
) -> Tuple[Dict, str, str]:
    if not tap_node_data or not tap_node:
        return {"display": "none"}, "building", "building"

    # Check if it's a right-click by checking the event type
    # For now, we'll show context menu on Ctrl+Click or long press
    node_id = tap_node_data.get("id")
    current_type = tap_node_data.get("type", "building")

    # Get position from tap event
    position = tap_node.get("renderedPosition", {"x": 0, "y": 0})
    
    # Position context menu near the node
    menu_style = {
        "display": "flex",
        "position": "fixed",
        "left": f"{position.get('x', 0) + 20}px",
        "top": f"{position.get('y', 0) + 20}px",
        "transform": "none",
    }

    return menu_style, current_type, node_id


@callback(
    Output("edit-label-dialog", "style"),
    Output("label-input", "value"),
    Input("graph", "tapNodeData"),
    State("last-tap", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def show_inline_edit(
    tap_node_data: Optional[Dict],
    last_tap: Dict,
    elements: List[Dict],
) -> Tuple[Dict, str]:
    if not tap_node_data:
        return {"display": "none"}, ""

    tapped_id = tap_node_data.get("id")
    timestamp = _now_ms()
    last_node = last_tap.get("node")
    last_timestamp = last_tap.get("timestamp", 0)

    # Double-click detection for inline editing
    if last_node == tapped_id and (timestamp - last_timestamp) < 400:
        current_label = tap_node_data.get("customLabel", "")
        return {"display": "flex"}, current_label

    return {"display": "none"}, ""


@callback(
    Output("context-menu-pos", "data"),
    Input("graph", "tapNode"),
    prevent_initial_call=True,
)
def update_menu_position(
    tap_node: Optional[Dict],
) -> Dict:
    if not tap_node:
        return {"x": 0, "y": 0}
    position = tap_node.get("renderedPosition", {"x": 0, "y": 0})
    return position


@callback(
    Output("elements-store", "data", allow_duplicate=True),
    Input("connect-mode", "value"),
    Input("graph", "tapNodeData"),
    State("elements-store", "data"),
    State("selected-store", "data"),
    prevent_initial_call=True,
)
def connect_nodes(
    connect_mode: List[str],
    tap_node_data: Optional[Dict],
    elements: List[Dict],
    selected: str,
) -> List[Dict]:
    if not tap_node_data or "on" not in connect_mode:
        return elements

    target_id = tap_node_data.get("id")
    if not target_id or target_id == selected:
        return elements

    existing_edges = {
        (edge["data"]["source"], edge["data"]["target"])
        for edge in elements
        if edge.get("data", {}).get("source")
    }
    if (selected, target_id) in existing_edges or (target_id, selected) in existing_edges:
        return elements

    return elements + [make_edge(selected, target_id)]


@callback(
    Output("collapsed-store", "data"),
    Input("toggle-collapse", "n_clicks"),
    State("collapsed-store", "data"),
    State("selected-store", "data"),
    prevent_initial_call=True,
)
def toggle_collapse(
    _n_clicks: int,
    collapsed: List[str],
    selected: str,
) -> List[str]:
    collapsed_set = set(collapsed)
    if selected in collapsed_set:
        collapsed_set.remove(selected)
    else:
        collapsed_set.add(selected)
    return list(collapsed_set)


@callback(
    Output("elements-store", "data", allow_duplicate=True),
    Output("edit-label-dialog", "style", allow_duplicate=True),
    Output("label-input", "value", allow_duplicate=True),
    Input("save-label", "n_clicks"),
    Input("cancel-label", "n_clicks"),
    State("label-input", "value"),
    State("selected-store", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def handle_label_edit(
    save_clicks: int,
    cancel_clicks: int,
    new_label: str,
    selected: str,
    elements: List[Dict],
) -> Tuple[List[Dict], Dict, str]:
    ctx = dash.callback_context
    if not ctx.triggered:
        return elements, {"display": "none"}, ""

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "cancel-label":
        return elements, {"display": "none"}, ""

    if trigger_id == "save-label" and new_label:
        updated: List[Dict] = []
        for element in elements:
            data = element.get("data", {})
            if data.get("id") == selected:
                type_label = data.get("typeLabel", "")
                combined_label = f"{type_label}\n{new_label}"
                updated_data = {**data, "label": combined_label, "customLabel": new_label}
                updated.append({**element, "data": updated_data})
            else:
                updated.append(element)
        return updated, {"display": "none"}, ""

    return elements, {"display": "none"}, ""


@callback(
    Output("elements-store", "data", allow_duplicate=True),
    Output("context-menu", "style", allow_duplicate=True),
    Input("context-apply", "n_clicks"),
    Input("context-cancel", "n_clicks"),
    State("context-type-select", "value"),
    State("selected-store", "data"),
    State("right-click-node", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def handle_context_menu(
    apply_clicks: int,
    cancel_clicks: int,
    type_key: str,
    selected: str,
    right_click_node: Optional[str],
    elements: List[Dict],
) -> Tuple[List[Dict], Dict]:
    ctx = dash.callback_context
    if not ctx.triggered:
        return elements, {"display": "none"}

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "context-cancel":
        return elements, {"display": "none"}

    if trigger_id == "context-apply":
        # Use right-click node if available, otherwise use selected
        target_node = right_click_node if right_click_node else selected
        updated: List[Dict] = []
        for element in elements:
            data = element.get("data", {})
            if data.get("id") == target_node:
                custom_label = data.get("customLabel", data.get("label", ""))
                type_label = TYPE_MAP[type_key].label
                combined_label = f"{type_label}\n{custom_label}"
                updated_data = {
                    **data,
                    "type": type_key,
                    "typeLabel": type_label,
                    "label": combined_label,
                    "color": TYPE_MAP[type_key].color,
                }
                updated.append({**element, "data": updated_data, "classes": type_key})
            else:
                updated.append(element)
        return updated, {"display": "none"}

    return elements, {"display": "none"}


@callback(
    Output("graph", "elements"),
    Output("graph", "layout"),
    Output("selection-label", "children"),
    Input("elements-store", "data"),
    Input("collapsed-store", "data"),
    Input("selected-store", "data"),
    Input("fit-btn", "n_clicks"),
    Input("layout-btn", "n_clicks"),
)
def sync_graph(
    elements: List[Dict],
    collapsed: List[str],
    selected: str,
    _fit_clicks: int,
    _layout_clicks: int,
) -> Tuple[List[Dict], Dict, str]:
    processed = apply_visibility(elements, set(collapsed))
    for element in processed:
        data = element.get("data", {})
        is_edge = "source" in data
        if not is_edge:
            type_key = data.get("type", "sensors")
            existing = element.get("classes", "")
            hidden_class = "hidden" if "hidden" in existing.split() else ""
            classes = f"{hidden_class} {type_key}".strip()
            if data.get("id") == selected:
                classes = f"selected {classes}".strip()
            element["classes"] = classes
    selected_label = "None"
    for element in processed:
        data = element.get("data", {})
        if data.get("id") == selected:
            type_label = data.get("typeLabel", "")
            custom_label = data.get("customLabel", "")
            selected_label = f"{type_label}: {custom_label}"
            break
    layout = {"name": "cose", "animate": True, "fit": True}
    return processed, layout, selected_label


if __name__ == "__main__":
    app.run_server(debug=True)
