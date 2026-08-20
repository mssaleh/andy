# Container services

Small HTTP services that run **inside** the `dustynv` inference containers on
the AGX. They are here rather than on the machine because they are part of the
deployment: the container supplies the model and the CUDA stack, and the file
in this directory supplies the only interface Andy's server speaks to.

Each is mounted read-only at `/svc` and run as the container's command, so no
derived image has to be built or maintained for a couple of routes.

| Service | Image | Port | Serves |
|---|---|---|---|
| `whisper_service.py` | `dustynv/whisper_trt` | 8881 | `POST /transcribe`, `GET /health` |
| `nanoowl_service.py` | `dustynv/nanoowl` | 8883 | `POST /detect`, `GET /health` |

They share a shape, and the reasons are the same in both cases:

- **A long-lived process, not a library call.** Both pay a large one-time cost
  to build or load a TensorRT engine, and both must keep the model resident to
  answer in the time a conversation allows.
- **Standard library only.** Neither image ships a web framework, and adding
  one would mean maintaining a derived image for two routes. Work is serialised
  on the GPU regardless, so a threaded stdlib server costs nothing.
- **A failure here cannot take the agent down.** They are separate processes
  behind HTTP, and the server treats an unreachable one as a provider that is
  not ready.

`ANDY_ASR_URL` and `ANDY_OWL_URL` are how the server finds them.
