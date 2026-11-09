const assert=require('node:assert/strict');
const {splitScripts}=require('../voice_mix/static/batch.js');
const numbered=Array.from({length:10},(_,i)=>`文案${i+1}：不同卖点${i+1}`).join('\n');
assert.equal(splitScripts(numbered).length,10);
assert.deepEqual(splitScripts('第一行\n第二行\n---\n另一条'),['第一行\n第二行','另一条']);
assert.equal(splitScripts('一句\n两句').length,1);
assert.equal(splitScripts('一条\n两条','line').length,2);
assert.equal(splitScripts('1.25元\n2.35元').length,1);
console.log('Batch parser regression checks passed');
