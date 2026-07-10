# 3D avatar asset licenses

The default avatars are from the **VALID** (Validated Avatar Library for
Inclusion and Diversity) set, converted to glTF by
[c-frame/valid-avatars-glb](https://github.com/c-frame/valid-avatars-glb)
(**MIT License** — freely redistributable). Original research library:
[xrtlab/Validated-Avatar-Library-for-Inclusion-and-Diversity---VALID](https://github.com/xrtlab/Validated-Avatar-Library-for-Inclusion-and-Diversity---VALID).

| File | Source avatar | License |
| --- | --- | --- |
| `valid_female_business.glb` | VALID `AIAN_F_1_Busi` | MIT (via c-frame/valid-avatars-glb) |
| `valid_male_business.glb`   | VALID `Asian_M_1_Busi` | MIT (via c-frame/valid-avatars-glb) |

## Lip-sync note

These VALID models carry SALSA-style phoneme morph targets (e.g. `AE_AA_h`,
`FV_h`, `KG_h`, `Kiss_h`), **not** the Oculus-viseme / ARKit blendshape names
the TalkingHead renderer drives. The avatars therefore **display correctly but
do not lip-sync out of the box**. To restore full lip-sync, either drop in an
avatar that carries Oculus visemes + ARKit blendshapes (e.g. your own
[Ready Player Me](https://readyplayer.me/) export) at the same paths, or add a
viseme→VALID morph-target mapping in the renderer.

The previous default models (Avaturn / Avatar SDK / Ready Player Me) were
licensed for non-commercial use only and were removed so this repository can be
MIT-clean and publicly redistributable.
