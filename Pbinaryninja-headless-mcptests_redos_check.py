import time
from binja_mcp.tools.strings import search_strings, STRING_REGEX_TIMEOUT_S
from binja_mcp.supervisor import Supervisor
from binja_mcp.mock_backend import MockString
from types import SimpleNamespace
import tempfile, os
sup = Supervisor(force_mock=True)
with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
    f.write(b'\x7fELF' + b'\x00'*64); p=f.name
bid=sup.open(p); bv=sup.get(bid).bv
bv.strings = [MockString(value='a'*120+'!', address=0x1000+i) for i in range(60)]
ctx=SimpleNamespace(request_context=SimpleNamespace(lifespan_context=SimpleNamespace(supervisor=sup)))
print(f'timeout={STRING_REGEX_TIMEOUT_S}s', flush=True)
t0=time.time()
try:
    r=search_strings(bid, ctx, pattern=r'(a+)+!extra', regex=True)
    print(f'NO_TIMEOUT total={r["total"]} elapsed={time.time()-t0:.2f}s', flush=True)
except TimeoutError:
    print(f'TIMEOUT_OK elapsed={time.time()-t0:.2f}s', flush=True)
sup.close_all(); os.unlink(p)
