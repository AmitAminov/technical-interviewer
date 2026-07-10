# 3D avatar asset licenses

All GLB files were copied from the
[met4citizen/TalkingHead](https://github.com/met4citizen/TalkingHead)
repository (repo code is MIT). The avatar model files themselves carry their
own licenses, recorded verbatim from the repo README ("Licenses, attributions
and notes"):

| File | Origin | License |
| --- | --- | --- |
| `avaturn.glb` | Created at [Avaturn](https://avaturn.me) | For **non-commercial use** (per the TalkingHead README attribution) |
| `avatarsdk.glb` | Created at [Avatar SDK](https://avatarsdk.com/) | For **non-commercial use** (per the TalkingHead README attribution) |
| `brunette.glb` | Created at [Ready Player Me](https://readyplayer.me/) | Free to all developers for **non-commercial use** under [CC BY-NC 4.0 DEED](https://creativecommons.org/licenses/by-nc/4.0/) — retired from the default set, kept only for the classic-renderer fallback path |

`avaturn.glb` and `avatarsdk.glb` are the two photo-realistic faces used by
default (matched to the female/male interviewer voices); both carry the full
Oculus viseme + ARKit blendshape sets required for lip-sync.

This project is a personal-use, non-commercial mock-interview app, which is
compatible with the terms above. If this app is ever commercialized, replace
these models (e.g. with your own Ready Player Me avatar or a CC0 model such
as the repo's `mpfb.glb`).
