'use strict';
// Offline evaluation of the actual rule template. No polkit daemon is contacted.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');
const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root,
    'd-i/forky/hooks/target/etc/polkit-1/rules.d/10-greetd-power.rules.tmpl'), 'utf8')
    .replaceAll('__INSTALLER_LABWC_GREETER_USER__', 'testgreeter');
let rule;
const Result = {YES: 'yes', NO: 'no', NOT_HANDLED: 'not-handled'};
vm.runInNewContext(source, {polkit: {Result, addRule: fn => {rule = fn;}}}, {timeout: 1000});
assert.strictEqual(typeof rule, 'function');
const helper = '/usr/local/libexec/greetd-power-action-root';
const subject = {user: 'testgreeter', local: true, active: true};
const action = (id, program) => ({id, lookup: key => key === 'program' ? program : undefined});
const cases = [
    ['exact helper', action('org.freedesktop.policykit.exec', helper), subject, Result.YES],
    ['helper with suffix', action('org.freedesktop.policykit.exec', helper + '-other'), subject, Result.NOT_HANDLED],
    ['helper with injected argument', action('org.freedesktop.policykit.exec', helper + ' reboot'), subject, Result.NOT_HANDLED],
    ['admin helper', action('org.freedesktop.policykit.exec', '/usr/local/libexec/labwc-admin-action-root'), subject, Result.NOT_HANDLED],
    ['no program', action('org.freedesktop.policykit.exec'), subject, Result.NOT_HANDLED],
    ['inactive greeter', action('org.freedesktop.policykit.exec', helper), {...subject, active: false}, Result.NO],
    ['nonlocal greeter', action('org.freedesktop.policykit.exec', helper), {...subject, local: false}, Result.NO],
    ['unknown local state', action('org.freedesktop.policykit.exec', helper), {user:'testgreeter',active:true}, Result.NO],
    ['other account', action('org.freedesktop.policykit.exec', helper), {...subject, user:'other'}, Result.NOT_HANDLED],
    ['virtual terminal switch', action('org.freedesktop.login1.chvt'), subject, Result.YES],
    ['other action', action('org.freedesktop.example.action'), subject, Result.NOT_HANDLED],
];
for (const base of ['power-off', 'reboot']) {
    for (const suffix of ['', '-multiple-sessions', '-ignore-inhibit']) {
        cases.push(['direct ' + base + suffix, action('org.freedesktop.login1.' + base + suffix), subject, Result.NO]);
    }
}
for (const [name, request, who, expected] of cases) {
    assert.strictEqual(rule(request, who), expected, name);
    console.log('PASS ' + name);
}
console.log(`${cases.length} authorization cases passed (offline JavaScript rule evaluation).`);
