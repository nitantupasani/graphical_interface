# graphical_interface

## Building Systems Graph UI

This project provides an interactive graph editor for modeling building systems with
nested, collapsible nodes, typed components, and connection drawing. The interface
is implemented in Python using Dash and Cytoscape for an aesthetic, dynamic layout.

### Features

- Click the canvas to add new nodes as children of the selected node.
- Right-click a node to focus it and assign a type from the sidebar.
- Enable connection mode to link two nodes.
- Toggle collapse to hide or expand nested subtrees.
- Zoom and pan across the graph; re-layout and fit-to-view controls are provided.

### Running the app

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the Dash server:

```bash
python app.py
```

Then open `http://127.0.0.1:8050` in your browser.
