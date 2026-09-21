import { Component } from '@odoo/owl';
import mediaDialog from '@web_editor/components/media_dialog/media_dialog';

export class RealisticWidget extends Component {
    static template = 'odoo18_realistic_addon.RealisticWidget';
    openMediaDialog() {
        return mediaDialog;
    }
}
