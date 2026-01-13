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
    data = {
        "id": node_id,
        "label": label,
        "type": type_key,
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
                "background-color": "data(color)",
                "label": "data(label)",
                "color": "#f8fafc",
                "text-valign": "center",
                "text-halign": "center",
                "text-outline-color": "#0f172a",
                "text-outline-width": 2,
                "font-size": 12,
                "width": 55,
                "height": 55,
            },
        },
        {
            "selector": "node.building",
            "style": {"width": 90, "height": 90, "font-size": 16},
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
        make_node("building", "Building", "building"),
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
                            "Tap the canvas to add nodes, then right-click a node to assign its type. "
                            "Select one node and then another to draw a connection. Double-tap a node "
                            "to collapse or expand its hierarchy."
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
                                html.Label("Assign Type"),
                                dcc.Dropdown(
                                    id="type-select",
                                    options=[
                                        {"label": node_type.label, "value": node_type.key}
                                        for node_type in NODE_TYPES
                                    ],
                                    value="building",
                                    clearable=False,
                                ),
                                html.Button("Apply Type", id="apply-type", n_clicks=0),
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
                                        html.Li("Click the canvas to create a child for the selected node."),
                                        html.Li("Right-click a node to focus it, then assign its type."),
                                        html.Li("Enable connection mode to link two nodes."),
                                        html.Li("Use mouse wheel or trackpad to zoom and pan."),
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
                        )
                    ]
                ),
            ],
        ),
        dcc.Store(id="elements-store", data=initial_elements()),
        dcc.Store(id="collapsed-store", data=[]),
        dcc.Store(id="selected-store", data="building"),
        dcc.Store(id="last-tap", data={"timestamp": 0, "node": None}),
    ],
)


@callback(
    Output("elements-store", "data"),
    Output("selected-store", "data"),
    Output("last-tap", "data"),
    Output("collapsed-store", "data", allow_duplicate=True),
    Input("graph", "tapNodeData"),
    Input("graph", "tapNode"),
    State("elements-store", "data"),
    State("selected-store", "data"),
    State("last-tap", "data"),
    State("collapsed-store", "data"),
    prevent_initial_call=True,
)
def handle_node_tap(
    tap_node_data: Optional[Dict],
    tap_node: Optional[Dict],
    elements: List[Dict],
    selected: str,
    last_tap: Dict,
    collapsed: List[str],
) -> Tuple[List[Dict], str, Dict, List[str]]:
    if not tap_node_data:
        return elements, selected, last_tap, collapsed

    tapped_id = tap_node_data.get("id")
    timestamp = _now_ms()
    last_node = last_tap.get("node")
    last_timestamp = last_tap.get("timestamp", 0)

    if last_node == tapped_id and (timestamp - last_timestamp) < 350:
        collapsed_set = set(collapsed)
        if tapped_id in collapsed_set:
            collapsed_set.remove(tapped_id)
        else:
            collapsed_set.add(tapped_id)
        return (
            elements,
            selected,
            {"node": tapped_id, "timestamp": timestamp},
            list(collapsed_set),
        )

    return elements, tapped_id, {"node": tapped_id, "timestamp": timestamp}, collapsed


@callback(
    Output("elements-store", "data", allow_duplicate=True),
    Output("selected-store", "data", allow_duplicate=True),
    Input("graph", "tap"),
    State("graph", "tapNodeData"),
    State("elements-store", "data"),
    State("selected-store", "data"),
    prevent_initial_call=True,
)
def handle_canvas_tap(
    tap_event: Optional[Dict],
    tap_node_data: Optional[Dict],
    elements: List[Dict],
    selected: str,
) -> Tuple[List[Dict], str]:
    if not tap_event or tap_node_data:
        return elements, selected

    position = tap_event.get("position") or {"x": 0, "y": 0}
    node_id = f"node-{uuid.uuid4().hex[:6]}"
    new_node = make_node(node_id, "New Node", "sensors", parent=selected, position=position)
    return elements + [new_node], node_id


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
    Input("apply-type", "n_clicks"),
    State("type-select", "value"),
    State("selected-store", "data"),
    State("elements-store", "data"),
    prevent_initial_call=True,
)
def apply_type(
    _n_clicks: int,
    type_key: str,
    selected: str,
    elements: List[Dict],
) -> List[Dict]:
    updated: List[Dict] = []
    for element in elements:
        data = element.get("data", {})
        if data.get("id") == selected:
            updated_data = {
                **data,
                "type": type_key,
                "label": TYPE_MAP[type_key].label,
                "color": TYPE_MAP[type_key].color,
            }
            updated.append({**element, "data": updated_data, "classes": type_key})
        else:
            updated.append(element)
    return updated


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
    Output("graph", "elements"),
    Output("graph", "layout"),
    Output("selection-label", "children"),
    Output("type-select", "value"),
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
) -> Tuple[List[Dict], Dict, str, str]:
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
    selected_type = "building"
    for element in processed:
        data = element.get("data", {})
        if data.get("id") == selected:
            selected_label = data.get("label", "")
            selected_type = data.get("type", "building")
    layout = {"name": "cose", "animate": True, "fit": True}
    return processed, layout, selected_label, selected_type


if __name__ == "__main__":
    app.run_server(debug=True)
