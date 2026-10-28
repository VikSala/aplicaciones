/** Browser-independent regression of both paths for archiving/discarding conversations. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/src/js/sale_ai_chat.js'), 'utf8');
const xml = fs.readFileSync(path.join(root, 'static/src/xml/sale_ai_chat.xml'), 'utf8');
function extract(start, end) {
    const a = source.indexOf(start);
    const b = source.indexOf(end, a + start.length);
    assert(a > 0 && b > a, `${start} not found`);
    return source.slice(a, b);
}
const newConversation = vm.runInNewContext(`({${extract('    requestNewConversation() {', '    async startNewConversation(')}}).requestNewConversation`, {
    SaleAIReplaceConversationDialog: 'dialog',
    _t: text => text,
});
function requestNew(current, composer = '', files = []) {
    const dialogs = [];
    const modes = [];
    const context = {
        state: { busy:false, sending:false, session:current, active:current, composer, pendingFiles:files },
        dialog: { add: (type,props) => dialogs.push({type,props}) },
        startNewConversation: (mode) => modes.push(mode || 'auto'),
    };
    newConversation.call(context);
    return { dialogs, modes };
}
for (const edit of [false,true]) {
    const result = requestNew({ id:42, edit_order_id:edit ? 77 : false, has_work:true });
    assert.equal(result.dialogs.length,1);
    const d = result.dialogs[0];
    assert.equal(d.type,'dialog');
    assert.equal(d.props.archiveLabel,'Archivar y empezar');
    assert.equal(d.props.discardLabel,'Descartar y empezar');
    d.props.onArchive(); d.props.onDiscard();
    assert.deepEqual(result.modes, ['archive','discard']);
}
assert.deepEqual(requestNew({id:42,edit_order_id:77,has_work:false}).modes,['auto']);
assert.equal(requestNew({id:42, edit_order_id:77,has_work:false},'texto').dialogs.length,1);
assert.equal(requestNew({id:42, edit_order_id:77,has_work:false},'',[{name:'file.mp3'}]).dialogs.length,1);
const footer = xml.split('<t t-name="sale_ai_assistant.SaleAIChat"')[0];
assert(!footer.includes('>Cancelar</button>'), 'No cancel button: the X closes the window');
assert(footer.indexOf('t-on-click="chooseArchive"') < footer.indexOf('t-on-click="chooseDiscard"'), 'Archive must appear first');
const newFn = extract('    async startNewConversation(', '    async showHistory(');
assert.match(newFn, /"assistant_panel_new", \[activeId, replaceMode\]/, 'Selected mode must reach the backend');
const py = fs.readFileSync(path.join(root, 'models/sale_ai_panel.py'), 'utf8');
assert.match(py, /def assistant_panel_new\(self, current_session_id=False, replace_mode="auto"\):/);
assert.match(py, /replace_mode == "archive"/);
assert.match(py, /current\.unlink\(\)/);
console.log('OK: 11.25 both dialogs, order of actions, no cancel button, archive/discard RPC and clean PV');
