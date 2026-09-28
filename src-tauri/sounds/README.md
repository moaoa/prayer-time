# Prayer sounds

One audio file per prayer. Supported formats: `.mp3`, `.wav`, `.ogg`, `.m4a`.

Expected filenames:

- `fajer.mp3`
- `dhuhr.mp3`
- `asr.mp3`
- `maghrib.mp3`
- `isha.mp3`

Sunrise is not used for the adhan alarm.

## Current sounds

These files are spoken Arabic announcements generated locally with
[Piper TTS](https://github.com/OHF-Voice/piper1-gpl) (voice `ar_JO-kareem-low`,
with tashkeel auto-diacritization).

Phrase: "حان الآن موعد أذان صلاة ..." (Fajr adds "الصلاة خير من النوم").

To regenerate or try other variations, run from the project root:

```bash
source .venv-piper/bin/activate
python scripts/generate_sounds_piper.py
```

Output packs land in `sounds_generated/<variation>/`; copy the chosen pack here.
