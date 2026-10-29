// The assertion harness: every test file reports its own count, and the count is PINNED. A test whose
// population silently shrinks (a loop that stops reaching things, a section commented out) prints the same
// "all passed" as one that is fine; done(expected) makes that red.
//   const { check, done } = require('./check.js')();
//   check(cond, 'what must hold, in words a reader can act on');
//   done(12, n => 'area: all ' + n + ' checks passed');
'use strict';
module.exports = function harness(){
  let fails = 0, executed = 0;
  return {
    check: (cond, msg) => { executed++; if (!cond){ fails++; console.log('FAIL ' + msg); } },
    done: (expected, summary) => {
      if (executed !== expected){
        console.log('FAIL this file ran ' + executed + ' assertions, not the ' + expected + ' it declares — a shrinking population must not read as a pass');
        fails++;
      }
      console.log(fails ? fails + ' failure(s), ' + executed + ' assertions' : summary(executed));
      process.exit(fails ? 1 : 0);
    }
  };
};
