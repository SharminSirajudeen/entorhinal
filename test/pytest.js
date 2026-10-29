// A mutant entry's runner fields for one pytest test: `expect` is pytest's own failure line, absent on a green run.
// No .pyc is written: Python trusts a .pyc whose source has the same size and mtime second, so a same-size mutant
// written within a second of the last one would run the previous mutant's bytecode (2 false results in 9 runs were seen).
// --basetemp in the shard's own copy: pytest keeps only its 3 newest run dirs under one shared root, so shards running
// at once deleted each other's tmp_path and a red test showed as ERROR, not the FAILED line.
'use strict';
module.exports = (file, test) => ({ mustFail:file, cmd:'PYTHONDONTWRITEBYTECODE=1 REPLAY=1 .venv/bin/python -m pytest --basetemp=.pytest-tmp ' + file, expect:'FAILED ' + file + '::' + test });
