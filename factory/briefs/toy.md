@planner Build the toy shared-counter service through all four stages as a dark-factory run. You are the lead seat: coordinate the band according to your mandate.

Track: toy
Repository: https://github.com/Ccyclop/toy-result (branch main). Every seat already has its own clone of it under /Users/tegi/Developer/hackathon/seats/<seat>.

Specifications. Read each one in full, and paste the text a seat needs into every handoff:
- M1 = stage 1: /Users/tegi/Developer/hackathon/dark-factory-wearedevs/toy/spec/stage-1.md
- M2 = stage 2: /Users/tegi/Developer/hackathon/dark-factory-wearedevs/toy/spec/stage-2.md
- M3 = stage 3: /Users/tegi/Developer/hackathon/dark-factory-wearedevs/toy/spec/stage-3.md
- M4 = stage 4: /Users/tegi/Developer/hackathon/dark-factory-wearedevs/toy/spec/stage-4.md

Folders:
- M1 works in and delivers stage-1/. Each later milestone starts by copying the previous stage folder to stage-N/, with no nested .git, and widening the copy. stage-N/ is both the working folder and the delivery folder, and it is frozen once released.
- Every stage folder is a complete service on its own, with a Dockerfile and a RUN.md whose command builds and starts it with no manual steps.
- A stage folder solves its own stage and not a later one: do not build later-stage behaviour early.
- Acceptance tests go in acceptance/ and attack scripts in adversary/, both outside the stage folders.

Stack: Python 3.12, FastAPI and uvicorn; the page is served by the same app as plain HTML and JavaScript, with every asset inside the image.

Runtime constraints: bind 0.0.0.0 on $PORT (default 8080); healthy within 60 s; 2 CPUs and 2 GiB; 5 s per request (10 s for reset); dependencies installed during the build; no network at run time.

Checks. They are a sample; build to the specification. Run them from the kickoff directory, with a new --out directory every time:
  cd /Users/tegi/Developer/hackathon/dark-factory-wearedevs && .venv/bin/python -m harness run --track toy --repo <your clone> --stage <N> --out /Users/tegi/Developer/hackathon/band-work/checks/<seat>-toy-s<N>-$(date +%s)
Use the default host mode while iterating. The integrator's release run adds --mode isolated and must print "claimed stage: N". On stages 1 and 3 the extra line for the next stage is expected to fail.

Done when all four stage folders are released. Then send me your FINAL REPORT.
