import createRasterPopup from '../classes/RasterPopup';

function popupFor(name, options = {}) {
    return createRasterPopup({
        name,
        opacity: 0.75,
        bounds: '-105, 39, -104, 40',
        onSwitchMode: jest.fn(),
        ...options
    });
}

describe('raster map popup', () => {
    it.each([
        '<img src=x onerror="window.compromised = true">',
        '</div><script>window.compromised = true</script><div>',
        '<svg onload="window.compromised = true"></svg>',
        '<button class="switchModeButton" onclick="window.compromised = true">fake</button>',
        'Flight & survey <north> "quoted" café 🚁'
    ])('renders task name as literal text: %s', name => {
        const popup = popupFor(name);
        expect(popup.querySelector('.title').textContent).toBe(name);
        expect(popup.querySelector('.title').children.length).toBe(0);
        expect(popup.querySelectorAll('img, script, svg, [onerror], [onload], [onclick]').length).toBe(0);
        expect(popup.querySelectorAll('.switchModeButton').length).toBe(1);
    });

    it('preserves the opacity slider, bounds, loading area and 3D control', () => {
        const onSwitchMode = jest.fn();
        const popup = popupFor('Survey', { onSwitchMode });
        expect(popup.className).toBe('infoWindow');
        const slider = popup.querySelector('#layerOpacity');
        expect(slider.type).toBe('range');
        expect(slider.value).toBe('0.75');
        expect(slider.min).toBe('0');
        expect(slider.max).toBe('1');
        expect(slider.step).toBe('0.01');
        expect(popup.querySelector('.popup-bounds').textContent).toBe('Bounds: [-105, 39, -104, 40]');
        expect(popup.querySelector('.popup-download-assets.loading .fa-spin')).not.toBeNull();
        const button = popup.querySelector('.switchModeButton');
        expect(button.type).toBe('button');
        expect(button.querySelector('.fa-cube')).not.toBeNull();
        expect(button.textContent.trim()).toBe('3D');
        button.click();
        expect(onSwitchMode).toHaveBeenCalledTimes(1);
    });

    it('renders bounds as text and does not create controls from metadata', () => {
        const popup = popupFor('Survey', { bounds: '<img src=x onerror="alert(1)">' });
        expect(popup.querySelector('.popup-bounds').textContent).toBe('Bounds: [<img src=x onerror="alert(1)">]');
        expect(popup.querySelector('img')).toBeNull();
    });
});
