export default function createRasterPopup({ name, opacity, bounds, onSwitchMode }) {
    const popup = document.createElement('div');
    popup.className = 'infoWindow';
    // Only static markup belongs here. Metadata is inserted through DOM properties.
    popup.innerHTML = `<div class="title"></div>
                      <div class="popup-opacity-slider">Opacity: <input id="layerOpacity" class="opacity" type="range" min="0" max="1" step="0.01" /></div>
                      <div class="popup-bounds"></div>
                      <div class="popup-download-assets loading">
                        <i class="fa loading fa-spin fa-sync fa-spin fa-fw"></i>
                      </div>
                      <button type="button" class="switchModeButton btn btn-sm btn-secondary">
                        <i class="fa fa-cube"></i> 3D
                      </button>`;
    popup.querySelector('.title').textContent = name;
    popup.querySelector('.opacity').value = opacity;
    popup.querySelector('.popup-bounds').textContent = `Bounds: [${bounds}]`;
    popup.querySelector('.switchModeButton').addEventListener('click', onSwitchMode);
    return popup;
}
