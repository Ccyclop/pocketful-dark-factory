@planner Build stage 1 of the pocketful service as a dark-factory run. You are the lead seat: coordinate the band according to your mandate. This dispatch covers milestone M1 only; later stages are dispatched separately.

Specification for this milestone (read it in full; it builds on the earlier stages, whose specifications are in the same folder):
- M1 = stage 1: /Users/tegi/Developer/hackathon/dark-factory-wearedevs/pocketful/spec/stage-1.md

Track: pocketful
Repository: https://github.com/Ccyclop/pocketful-dark-factory (branch main). Every seat already has its own clone of it under /Users/tegi/Developer/hackathon/seats/<seat>.

Folders:
- Milestone MN works in and delivers stage-N/. Every milestone after the first starts by copying the previous stage folder to stage-N/, with no nested .git, and widening the copy. stage-N/ is both the working folder and the delivery folder, and it is frozen once released.
- Every stage folder is a complete service on its own, with a Dockerfile and a RUN.md whose command builds and starts it with no manual steps.
- A stage folder solves its own stage and not a later one: do not build later-stage behaviour early. Each stage folder is checked against every earlier stage's suite and must still pass them.
- Acceptance tests go in acceptance/ and attack scripts in adversary/, both outside the stage folders.

Stack: Python 3.12, FastAPI and uvicorn, SQLite from the standard library with every write in a transaction. Browser screens are served by the same app as HTML, CSS and plain JavaScript, with every font, script and stylesheet inside the image. Screens are judged for being coherent, presentation-ready, responsive and clear in every state the stage-2 specification identifies; code for being maintainable by another developer.

Runtime constraints (stage 1, section 2): bind 0.0.0.0 on $PORT (default 8080); healthy within 60 s of start; 2 vCPU and 2 GiB; up to 50 requests in flight; 5 s per request (10 s for the reset endpoint); dependencies installed during the build; no outbound network at run time; state need not survive a restart.

Checks. They cover only part of each stage, and the rest is judged from the specification, so a green check run is not evidence that a stage is done: re-read the stage's specification and test what the checks never ask. Run them from the kickoff directory, with a new --out directory every time:
  cd /Users/tegi/Developer/hackathon/dark-factory-wearedevs && .venv/bin/python -m harness run --track pocketful --repo <your clone> --stage <N> --out /Users/tegi/Developer/hackathon/band-work/checks/<seat>-pf-s<N>-$(date +%s)
Use the default host mode while iterating. The integrator's release run adds --mode isolated and must print "claimed stage: N". The extra line for the next stage's suite is expected to fail.

Keep handoffs complete but lean: paste the specification text a work item covers, not the whole specification every time.

Done when stage-1/ is released, or a blocker is recorded. Then send me your FINAL REPORT for M1 and stop until the next dispatch.
