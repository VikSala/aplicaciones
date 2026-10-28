/** Browser-independent checks of real Odoo OWL handlers and three-choice dialog. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/src/js/sale_ai_chat.js'), 'utf8');
const xml = fs.readFileSync(path.join(root, 'static/src/xml/sale_ai_chat.xml'), 'utf8');
const panel = fs.readFileSync(path.join(root, 'models/sale_ai_panel.py'), 'utf8');
const edit = fs.readFileSync(path.join(root, 'models/sale_ai_quote_edit.py'), 'utf8');
const modalType = 'SaleAIReplaceConversationDialog';
const start = source.indexOf('    requestLoadQuotation() {');
const end = source.indexOf('    async loadQuotation(', start);
assert(start > 0 && end > start);
const handler = vm.runInNewContext(`({ ${source.slice(start,end)} }).requestLoadQuotation`, {
    SaleAIReplaceConversationDialog: modalType,
    _t: text => text,
});
function test(current, composer='', files=[], id=51) {
    const calls=[];
    const dialogs=[];
    const ctx={readonly:false,state:{busy:false,sending:false,currentPVId:id,active:current,session:current,composer,pendingFiles:files},
        loadQuotation: (...args)=>calls.push(args),dialog:{add:(type,config)=>dialogs.push({type,config})}};
    handler.call(ctx);
    return {calls,dialogs};
}
let result = test({id:9,edit_order_id:51,has_work:false});
assert.deepEqual(result.calls,[[51,'auto']]);
assert.equal(result.dialogs.length,0,'Fresh loaded PV should be replaceable silently');
result = test({id:9,edit_order_id:51,has_work:true});
assert.equal(result.calls.length,0);
assert.equal(result.dialogs.length,1);
assert.equal(result.dialogs[0].type,modalType);
result.dialogs[0].config.onArchive();
result.dialogs[0].config.onDiscard();
assert.deepEqual(result.calls,[[51,'archive'],[51,'discard']]);
result = test({id:9,edit_order_id:52,has_work:true},'',[],51);
assert.equal(result.dialogs.length,1,'Existing other PV with work must ask');
result = test({id:9,edit_order_id:51,has_work:false},'Mensaje pendiente');
assert.equal(result.dialogs.length,1,'Unsent message must not be discarded silently');
result = test({id:9,edit_order_id:51,has_work:false},'',[{name:'voice.mp3'}]);
assert.equal(result.dialogs.length,1,'Pending audio must not be discarded silently');
result = test({id:9,edit_order_id:51,has_work:false},'',[],0);
assert.equal(result.calls.length,0,'No PV opened');
// The editor sometimes refreshes state.session while state.active remains
// stale: never mistake a modified draft for an untouched PV.
let stale = test({id:9,edit_order_id:51,has_work:false});
const currentSession = {id:9,edit_order_id:51,has_work:true};
const alerts=[];
handler.call({readonly:false,state:{busy:false,sending:false,currentPVId:51,active:{id:9,edit_order_id:51,has_work:false},session:currentSession,composer:'',pendingFiles:[]},
    loadQuotation:()=>{throw new Error('must confirm')},dialog:{add:(type,config)=>alerts.push(config)}});
assert.equal(alerts.length,1,'Use latest session snapshot when prompt is required');
assert.match(xml,/t-name="sale_ai_assistant\.SaleAIReplaceConversationDialog"/);
assert.match(xml,/t-on-click="chooseArchive">Archivar y cargar/);
assert.match(xml,/t-on-click="chooseDiscard">Descartar y cargar/);
assert.match(xml,/t-on-click="props\.close">Cancelar/);
assert.match(source,/replaceMode === "archive", replaceMode === "discard"/);
assert.match(panel,/info\["has_work"\] = self\._panel_session_has_work\(session\)/);
assert.match(panel,/current\.edit_order_id and self\._panel_session_has_work\(current\)/);
assert.match(edit,/has_work = self\._panel_session_has_work\(current\)/);
console.log('OK: 11.24 three choices, clean PV, pending content, safe backend contract');
