import sys, json
from . import paper, report, sweep
def main(a):
    cmd = a[0] if a else "paper-tick"
    if cmd == "paper-tick": paper.tick(); report.build(); print("paper tick ok")
    elif cmd == "sweep": sweep.run(quick="--quick" in a); report.build()
    elif cmd == "report": report.build(); print("report ok")
    elif cmd == "register": paper.register(a[1], json.loads(a[2]), note=a[3] if len(a) > 3 else "", risk=a[4] if len(a) > 4 else "low"); print("registered")
    else: print("commands: paper-tick | sweep [--quick] | report | register NAME CONFIG_JSON [note] [risk]")
if __name__ == "__main__": main(sys.argv[1:])
