// Isolated frontend tests: no Odoo browser runtime required.
const fs = require('fs');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../static/src/js/sale_ai_chat.js'), 'utf8');
const restoreSrc = source.split('    restoreFailedSubmission(target, temporaryId, content, preserveComposer) {')[1].split('\n    async submitContent(')[0].trim().replace(/\}\s*$/, '');
const submitSrc = source.split('    async submitContent(raw, preserveComposer = false) {')[1].split('\n    async retryLastReply()')[0].trim().replace(/\}\s*$/, '');
const restore = new Function('target', 'temporaryId', 'content', 'preserveComposer', restoreSrc);
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const submit = new AsyncFunction('raw','preserveComposer',submitSrc);
global._t = text => text;
function context(call) {
 const session = {id: 8, messages: [], draft: false};
 const files = [{name:'audio.mp3',data:'SUQz'}];
 const obj = {
  state: {pendingFiles: files, pendingFileSessionId:8, composer:'Reformula el texto descriptivo en base a estos audios', sending:false, busy:false, aiError:'', uploadError:'', session, active:session},
  readonly:false,
  orm:{call},
  notification:{notices:[],add(s) {this.notices.push(s)}},
  draftSignature:()=>'',
  restoreFailedSubmission:restore,
  notifyError:()=>{},
  showPreviewAfterDraftChange:()=>{},
 };
 return obj;
}
(async() => {
 const rejection = context(async () => ({file_error:'Vercel rechazó el archivo (HTTP 415)'}));
 await submit.call(rejection,rejection.state.composer,false);
 assert.equal(rejection.state.composer,'Reformula el texto descriptivo en base a estos audios');
 assert.equal(rejection.state.pendingFiles.length,1);
 assert.deepEqual(rejection.state.session.messages,[]);
 assert.match(rejection.state.uploadError,/HTTP 415/);
 assert.equal(rejection.state.sending,false);
 let called=0;
 const rpcFailure = context(async (model,method) => {
   if (method==='assistant_panel_send') {called++; throw Error('RPC_ERROR')}
   return {id:8,messages:[],draft:false};
 });
 await submit.call(rpcFailure,rpcFailure.state.composer,false);
 assert.equal(called,1);
 assert.equal(rpcFailure.state.composer,'Reformula el texto descriptivo en base a estos audios');
 assert.equal(rpcFailure.state.pendingFiles.length,1);
 assert.equal(rpcFailure.state.session.messages.length,0);
 assert.match(rpcFailure.state.uploadError,/Odoo/);
 assert.equal(rpcFailure.state.sending,false);
 const success = context(async () => ({id:24,role:'user',content:'ok',created_at:'',session_name:'Chat',draft:false}));
 await submit.call(success,success.state.composer,false);
 assert.equal(success.state.composer,'');
 assert.equal(success.state.pendingFiles.length,0);
 assert.equal(success.state.session.messages[0].id,24);
 assert.equal(success.state.uploadError,'');
 console.log('11.18 JS: error de archivo, fallo RPC y éxito conservan o limpian el borrador correctamente.');
})().catch(error=>{console.error(error);process.exitCode=1});
