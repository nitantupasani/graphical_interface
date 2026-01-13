from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

import dash
from dash import Dash, Input, Output, State, callback, dcc, html, no_update
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
    combined_label = f"{label}\n{type_label}"
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


def tint_color(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def default_stylesheet() -> List[Dict]:
    stylesheet = [
        {
            "selector": "node",
            "style": {
                "shape": "round-rectangle",
                "background-color": "#ffffff",
                "border-width": 2,
                "border-color": "data(color)",
                "label": "data(label)",
                "color": "#0f172a",
                "text-valign": "center",
                "text-halign": "center",
                "text-wrap": "wrap",
                "text-max-width": "110px",
                "font-size": 10,
                "font-weight": 600,
                "line-height": 1.2,
                "width": 120,
                "height": 72,
                "padding": 8,
                "border-radius": 14,
                "shadow-blur": 12,
                "shadow-color": "#94a3b8",
                "shadow-opacity": 0.35,
                "shadow-offset-x": 0,
                "shadow-offset-y": 4,
            },
        },
        {
            "selector": "node.building",
            "style": {
                "width": 160,
                "height": 96,
                "font-size": 11,
                "padding": 10,
                "text-max-width": "140px",
            },
        },
        {
            "selector": "edge",
            "style": {
                "width": 2,
                "line-color": "#cbd5e1",
                "curve-style": "bezier",
                "target-arrow-color": "#cbd5e1",
                "target-arrow-shape": "triangle",
            },
        },
        {"selector": ".selected", "style": {"border-width": 3, "border-color": "#2563eb"}},
        {"selector": ".hidden", "style": {"display": "none"}},
    ]
    for node_type in NODE_TYPES:
        alpha = 0.1 if node_type.key == "building" else 0.14
        stylesheet.append(
            {
                "selector": f'node[type = "{node_type.key}"]',
                "style": {"border-color": node_type.color},
            }
        )
    return stylesheet


def initial_elements() -> List[Dict]:
    node_id = "node-root"
    return [make_node(node_id, "Building", "building")]


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


def build_hierarchy_view(elements: List[Dict]) -> html.Ul:
    nodes = {el["data"]["id"]: el["data"] for el in elements if "source" not in el.get("data", {})}
    children_map = build_children_map(elements)
    root_nodes = [node_id for node_id, data in nodes.items() if "parent" not in data]

    def render_list(node_ids: Iterable[str]) -> html.Ul:
        items: List[html.Li] = []
        for node_id in node_ids:
            data = nodes.get(node_id, {})
            label = data.get("customLabel", data.get("label", ""))
            type_label = data.get("typeLabel", "")
            children = children_map.get(node_id, [])
            items.append(
                html.Li(
                    [
                        html.Div(
                            [
                                html.Span(label, className="hierarchy-title"),
                                html.Span(type_label, className="hierarchy-type"),
                            ],
                            className="hierarchy-row",
                        ),
                        render_list(children) if children else None,
                    ],
                    className="hierarchy-node",
                )
            )
        return html.Ul(items, className="hierarchy-list")

    if not root_nodes:
        return html.Ul([html.Li("No nodes yet.", className="hierarchy-empty")], className="hierarchy-list")

    return render_list(root_nodes)


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
                            "Double-click a node to add a child. Right-click a node to edit its title or change type. "
                            "Enable connection mode to link nodes."
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
                        html.Div(
                            className="panel hierarchy",
                            children=[
                                html.H3("Hierarchy"),
                                html.Div(id="hierarchy-tree", className="hierarchy-tree"),
                            ],
                        ),
                        html.H2("Node Types"),
                        html.Ul(legend_items(), id="legend"),
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
                                        html.Li("Double-click a node to add a child."),
                                        html.Li("Right-click a node to edit or change type."),
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
                            contextMenu=[
                                {
                                    "id": "edit-title",
                                    "label": "Edit title",
                                    "availableOn": ["node"],
                                },
                                {
                                    "id": "change-type",
                                    "label": "Change node type",
                                    "availableOn": ["node"],
                                },
                            ],
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
        dcc.Store(id="right-click-node", data=None),
        dcc.Store(id="canvas-click-store", data=None),
        html.Div(id="selection-label", className="selection", style={"display": "none"}),
        html.Div(
            style={"display": "none"},
            children=[
                html.Button("Edit Title", id="edit-title-btn", n_clicks=0),
                html.Button("Change Type", id="show-type-menu", n_clicks=0),
                html.Button("Toggle Collapse", id="toggle-collapse", n_clicks=0),
                html.Button("Canvas DblClick", id="canvas-dblclick", n_clicks=0),
            ],
        ),
        html.Div(
            id="context-menu",
            className="context-menu",
            style={"display": "none"},
            children=[
                html.H4("Change Node Type"),
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
                html.H4("Edit Title"),
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

app.clientside_callback(
    """
    function(n_clicks) {
        if (!n_clicks) {
            return window.dash_clientside.no_update;
        }
        const payload = window._canvasDblClick;
        if (!payload || payload.x === undefined || payload.y === undefined) {
            return window.dash_clientside.no_update;
        }
        return {
            x: payload.x,
            y: payload.y,
            timeStamp: payload.timeStamp || Date.now()
        };
    }
    """,
    Output("canvas-click-store", "data"),
    Input("canvas-dblclick", "n_clicks"),
    prevent_initial_call=True,
)


@callback(
    Output("elements-store", "data"),
    Output("selected-store", "data", allow_duplicate=True),
    Output("last-tap", "data"),
    Input("graph", "tapNodeData"),
    State("graph", "tapNode"),
    State("elements-store", "data"),
    State("selected-store", "data"),
    State("last-tap", "data"),
    prevent_initial_call=True,
)
def handle_node_tap(
    tap_node_data: Optional[Dict],
    tap_node: Optional[Dict],
    elements: List[Dict],
    selected: str,
    last_tap: Dict,
) -> Tuple[List[Dict], str, Dict]:
    if not tap_node_data:
        return elements, selected, last_tap

    tapped_id = tap_node_data.get("id")
    timestamp = _now_ms()
    last_node = last_tap.get("node")
    last_timestamp = last_tap.get("timestamp", 0)

    if last_node == tapped_id and (timestamp - last_timestamp) < 650:
        position = None
        if tap_node:
            position = tap_node.get("position")
        if position:
            position = {
                "x": position.get("x", 0) + 60,
                "y": position.get("y", 0) + 40,
            }
        node_id = f"node-{uuid.uuid4().hex[:6]}"
        new_node = make_node(node_id, "New Node", "sensors", parent=tapped_id, position=position)
        return elements + [new_node], node_id, {"node": node_id, "timestamp": 0}

    return elements, tapped_id, {"node": tapped_id, "timestamp": timestamp}


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
    Output("elements-store", "data", allow_duplicate=True),
    Input("canvas-click-store", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def handle_canvas_double_click(
    canvas_click: Optional[Dict],
    elements: List[Dict],
) -> List[Dict]:
    if not canvas_click:
        return elements

    x = canvas_click.get("x")
    y = canvas_click.get("y")
    if x is None or y is None:
        return elements

    node_id = f"node-{uuid.uuid4().hex[:6]}"
    new_node = make_node(
        node_id,
        "New Node",
        "sensors",
        position={"x": x, "y": y},
    )
    return elements + [new_node]


@callback(
    Output("hierarchy-tree", "children"),
    Input("elements-store", "data"),
)
def update_hierarchy(elements: List[Dict]) -> html.Ul:
    return build_hierarchy_view(elements)


@callback(
    Output("context-menu", "style"),
    Output("context-type-select", "value"),
    Output("right-click-node", "data"),
    Output("edit-label-dialog", "style"),
    Output("label-input", "value"),
    Output("selected-store", "data", allow_duplicate=True),
    Input("graph", "contextMenuData"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def handle_context_action(
    context_data: Optional[Dict],
    elements: List[Dict],
) -> Tuple[Dict, str, Optional[str], Dict, str, str]:
    if not context_data:
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )

    menu_item = context_data.get("menuItemId")
    node_id = context_data.get("elementId")

    current_type = "building"
    current_label = ""
    for element in elements:
        data = element.get("data", {})
        if data.get("id") == node_id:
            current_type = data.get("type", "building")
            current_label = data.get("customLabel", data.get("label", ""))
            break

    if menu_item == "edit-title":
        return (
            {"display": "none"},
            no_update,
            node_id,
            {"display": "flex"},
            current_label,
            node_id,
        )

    if menu_item == "change-type":
        return (
            {"display": "flex", "left": "50%", "top": "50%", "transform": "translate(-50%, -50%)"},
            current_type,
            node_id,
            {"display": "none"},
            "",
            node_id,
        )

    return (
        {"display": "none"},
        no_update,
        node_id,
        {"display": "none"},
        "",
        node_id,
    )


@callback(
    Output("context-menu", "style", allow_duplicate=True),
    Output("context-type-select", "value", allow_duplicate=True),
    Output("right-click-node", "data", allow_duplicate=True),
    Input("show-type-menu", "n_clicks"),
    State("selected-store", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def show_type_dialog(
    _clicks: int,
    selected: str,
    elements: List[Dict],
) -> Tuple[Dict, str, Optional[str]]:
    current_type = "building"
    for element in elements:
        data = element.get("data", {})
        if data.get("id") == selected:
            current_type = data.get("type", "building")
            break
    return (
        {"display": "flex", "left": "50%", "top": "50%", "transform": "translate(-50%, -50%)"},
        current_type,
        selected,
    )


@callback(
    Output("edit-label-dialog", "style", allow_duplicate=True),
    Output("label-input", "value", allow_duplicate=True),
    Output("selected-store", "data", allow_duplicate=True),
    Input("edit-title-btn", "n_clicks"),
    State("selected-store", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def show_edit_dialog(
    _clicks: int,
    selected: str,
    elements: List[Dict],
) -> Tuple[Dict, str, str]:
    current_label = ""
    for element in elements:
        data = element.get("data", {})
        if data.get("id") == selected:
            current_label = data.get("customLabel", data.get("label", ""))
            break
    return {"display": "flex"}, current_label, selected


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
    selected: Optional[str],
) -> List[str]:
    if not selected:
        return collapsed
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
    selected: Optional[str],
    elements: List[Dict],
) -> Tuple[List[Dict], Dict, str]:
    ctx = dash.callback_context
    if not ctx.triggered:
        return elements, {"display": "none"}, ""

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger_id == "cancel-label":
        return elements, {"display": "none"}, ""

    if trigger_id == "save-label" and new_label and selected:
        updated: List[Dict] = []
        for element in elements:
            data = element.get("data", {})
            if data.get("id") == selected:
                type_label = data.get("typeLabel", "")
                combined_label = f"{new_label}\n{type_label}"
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
    selected: Optional[str],
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
        if not target_node:
            return elements, {"display": "none"}
        if type_key == "building":
            existing_building = any(
                element.get("data", {}).get("type") == "building"
                and element.get("data", {}).get("id") != target_node
                for element in elements
            )
            if existing_building:
                return elements, {"display": "none"}
        updated: List[Dict] = []
        for element in elements:
            data = element.get("data", {})
            if data.get("id") == target_node:
                custom_label = data.get("customLabel", data.get("label", ""))
                type_label = TYPE_MAP[type_key].label
                combined_label = f"{custom_label}\n{type_label}"
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
    selected: Optional[str],
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
        if selected and data.get("id") == selected:
            type_label = data.get("typeLabel", "")
            custom_label = data.get("customLabel", "")
            selected_label = f"{type_label}: {custom_label}"
            break
    layout = {"name": "cose", "animate": True, "fit": True}
    return processed, layout, selected_label


if __name__ == "__main__":
    app.run_server(debug=True)
