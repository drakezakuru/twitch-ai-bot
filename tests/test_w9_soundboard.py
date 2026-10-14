from pathlib import Path
from app.widget_bindings import validate_widget_action

def test_soundboard_contract():
    assert validate_widget_action('soundboard','play_track:12') is None
    assert validate_widget_action('soundboard','play_track:no') == 'unknown_action'
    html=Path('widgets/soundboard/index.html').read_text()
    assert '/ws' in html and '/api/widgets/public/soundboard/tracks/' in html


def test_soundboard_panel_upload_inventory_play():
    panel=Path('templates/partials/widgets.html').read_text()
    js=Path('static/app/07_widgets.js').read_text()
    assert 'id="soundboardFile"' in panel and 'id="soundboardInventory"' in panel
    assert 'type="file" multiple' in panel
    assert 'src="/widget/soundboard"' in panel
    for name in (
        'waSoundboardUpload', 'waSoundboardLoad', 'waSoundboardPlay',
        'waSoundboardStop', 'waSoundboardSave', 'waSoundboardDelete',
        'waSoundboardBind',
    ):
        assert f'function {name}' in js or f'async function {name}' in js
    assert "form.append('files', file)" in js
    i18n=Path('static/app.js').read_text()
    for key in (
        'soundboard.hint', 'soundboard.upload_label', 'soundboard.play',
        'soundboard.bind', 'soundboard.stop', 'soundboard.name',
        'soundboard.volume', 'soundboard.cooldown', 'soundboard.order',
        'soundboard.upload_result', 'soundboard.stopped',
        'soundboard.delete_confirm',
    ):
        assert i18n.count("'"+key+"'")==3
