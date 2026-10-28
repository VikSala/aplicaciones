/** Standalone regression checks for Odoo 18 active quotation detection. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../static/src/js/sale_ai_chat.js"), "utf8");

assert.doesNotMatch(source, /this\.router\s*=\s*useService/, "no router service dependency");
assert.match(source, /useBus\(this\.env\.bus, "ACTION_MANAGER:UI-UPDATED"/, "refresh after view mount");
assert.match(source, /this\.action\?\.currentController/, "uses Odoo 18 action service");

// Execute the real method (not a rewritten copy) with mocked Odoo 18 action controllers.
const begin = source.indexOf('    getCurrentPVId() {');
const end = source.indexOf('    async refreshCurrentPV() {', begin);
assert(begin !== -1 && end > begin, "method exists");
const method = source.slice(begin, end).trim();
const getCurrentPVId = vm.runInNewContext(`({ ${method} }).getCurrentPVId`);
function actionController({model = "sale.order", type = "form", resId = 42, stateId, actionType = "ir.actions.act_window"} = {}) {
    return { action: {type: actionType, res_model: model},
        props: {resModel: model, type, resId},
        currentState: stateId === undefined ? {resId} : {resId: stateId} };
}
function resolve(ctrl) {
    return getCurrentPVId.call({action: {currentController: ctrl}});
}
assert.equal(resolve(actionController()), 42, "quotation form");
assert.equal(resolve(actionController({resId: 42, stateId: 51})), 51, "form pager follows current record");
assert.equal(resolve(actionController({resId: 42, stateId: null})), 42, "fallback if state not ready");
assert.equal(resolve(actionController({type: "list"})), false, "not on list views");
assert.equal(resolve(actionController({model: "res.partner"})), false, "not on other models");
assert.equal(resolve(actionController({resId: "new"})), false, "not on unsaved records");
assert.equal(resolve(actionController({resId: -1})), false, "not on invalid IDs");
assert.equal(resolve(actionController({actionType: "ir.actions.client"})), false, "not on client actions");
assert.equal(resolve(null), false, "initial render before action mounted");
assert.equal(resolve({action: {type: "ir.actions.act_window", res_model: "sale.order"}, props: {resModel: "sale.order", type: "form", resId: 37}}), 37, "valid if state unavailable");
console.log("OK: 11.21 active quotation detection and no missing router service");
