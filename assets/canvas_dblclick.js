document.addEventListener("DOMContentLoaded", () => {
  const graph = document.getElementById("graph");
  if (!graph) {
    return;
  }

  graph.addEventListener("dblclick", (event) => {
    if (!window.cy) {
      return;
    }

    const rect = graph.getBoundingClientRect();
    const renderedX = event.clientX - rect.left;
    const renderedY = event.clientY - rect.top;
    const pan = window.cy.pan();
    const zoom = window.cy.zoom();
    const x = (renderedX - pan.x) / zoom;
    const y = (renderedY - pan.y) / zoom;

    window._canvasDblClick = { x, y, timeStamp: Date.now() };

    const trigger = document.getElementById("canvas-dblclick");
    if (trigger) {
      trigger.click();
    }
  });
});
