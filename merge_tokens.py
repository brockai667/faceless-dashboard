# -*- coding: utf-8 -*-
"""
Zlucenie tokenov pre Render (IG_TOKENS_JSON / TIKTOK_TOKENS_JSON) bez rucneho upravovania JSON.
Spusta USER. Tokeny sa NIKDY nevypisuju ani neukladaju na disk - idu len cez schranku.

    1) Render -> sluzba facelessfactory-dashboard -> Environment: klikni do hodnoty premennej, Ctrl+A, Ctrl+C
    2) python merge_tokens.py ig          (alebo: python merge_tokens.py tiktok)
    3) v Render do toho isteho pola: Ctrl+A, Ctrl+V a uloz (Save, rebuild and deploy)

Skript precita schranku (aktualna hodnota z Renderu) + lokalny subor s tokenmi, zluci ich
(nove ucty prida, pri rovnakom ucte necha cerstvejsi token) a vysledok vlozi spat do schranky.
Vypisuje len MENA uctov, zdroj a (pri Instagrame) pocet dni do expiracie.
"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
FILES = {"ig": ("ig_tokens.json", "IG_TOKENS_JSON"), "tiktok": ("tiktok_tokens.json", "TIKTOK_TOKENS_JSON")}


def clip_get():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"], capture_output=True)
    return r.stdout.decode("utf-8", "replace").strip()


def clip_set(text):
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "[Console]::InputEncoding=[Text.Encoding]::UTF8; $t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t"],
                   input=text.encode("utf-8"), check=True)


def ig_exp(v):
    """cas expiracie IG tokenu (epoch); bez _refreshed_at = neznamy -> 0"""
    return (v.get("_refreshed_at") or 0) + (v.get("expires_in") or 0) if v.get("_refreshed_at") else 0


def merge_ig(render, local):
    """Instagram: zjednotenie podla mena uctu, pri zhode vyhra neskorsia expiracia; premenovany ucet (rovnake user_id) = 1 zaznam."""
    out, src = {}, {}
    for name, v in render.items():
        out[name], src[name] = v, "Render"
    for name, v in local.items():
        if name not in out:
            out[name], src[name] = v, "lokalny (novy ucet)"
        elif ig_exp(v) > ig_exp(out[name]):
            out[name], src[name] = v, "lokalny (cerstvejsi)"
    by_uid = {}
    for name in list(out):
        uid = str(out[name].get("user_id") or "")
        if not uid:
            continue
        other = by_uid.get(uid)
        if other is None:
            by_uid[uid] = name
            continue
        keep, drop = (name, other) if ig_exp(out[name]) >= ig_exp(out[other]) else (other, name)
        out.pop(drop); src.pop(drop, None)
        src[keep] += f", nahradil stare meno {drop}"
        by_uid[uid] = keep
    return out, src


def _same_tk(a, b):
    return a.get("access_token") == b.get("access_token") and a.get("refresh_token") == b.get("refresh_token")


def merge_tiktok(render, local, ask):
    """TikTok: tokeny nemaju cas -> novy ucet sa prida, pri konflikte (rovnaky stitok alebo rovnake open_id) rozhodne user cez ask(otazka)."""
    out, src = {}, {}
    for label, v in render.items():
        out[label], src[label] = v, "Render"
    for label, v in local.items():
        twin = label if label in out else next(
            (k for k, o in out.items() if v.get("open_id") and o.get("open_id") == v.get("open_id")), None)
        if twin is None:
            out[label], src[label] = v, "lokalny (novy ucet)"
        elif _same_tk(v, out[twin]):
            continue
        elif ask(f"Ucet '{label}' je uz v Renderi" + (f" (pod menom '{twin}')" if twin != label else "") +
                 ". Pouzit LOKALNY token (ak si ho prave znova autorizoval)? [a/N]: "):
            out.pop(twin); src.pop(twin, None)
            out[label], src[label] = v, "lokalny (znova autorizovany)" + (f", nahradil {twin}" if twin != label else "")
    return out, src


def _ask(q):
    return input(q).strip().lower() in ("a", "ano", "y", "yes")


def main():
    kind = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if kind not in FILES:
        print("Pouzitie: python merge_tokens.py ig | tiktok"); return 1
    fname, env = FILES[kind]
    lpath = os.path.join(ROOT, fname)
    if not os.path.exists(lpath):
        print(f"Lokalny subor {fname} neexistuje - najprv autorizuj ucet."); return 1
    try:
        local = json.load(open(lpath, encoding="utf-8"))
    except Exception as e:
        print(f"Lokalny subor {fname} sa neda precitat ({type(e).__name__})."); return 1
    try:
        render = json.loads(clip_get() or "null")
    except Exception:
        render = None
    if not isinstance(render, dict) or not all(isinstance(v, dict) for v in render.values()):
        print(f"V schranke nie je hodnota {env} z Renderu (najprv ju tam skopiruj: klik do pola, Ctrl+A, Ctrl+C).")
        if not _ask("Pokracovat LEN s lokalnymi tokenmi (premenna v Renderi je prazdna)? [a/N]: "):
            return 1
        render = {}
    out, src = merge_ig(render, local) if kind == "ig" else merge_tiktok(render, local, _ask)
    clip_set(json.dumps(out, ensure_ascii=False))
    now = time.time()
    print(f"\n{env}: {len(out)} uctov (Render mal {len(render)}, lokalne {len(local)})")
    for name in sorted(out, key=str.lower):
        extra = ""
        if kind == "ig":
            e = ig_exp(out[name])
            extra = " | platnost neznama" if not e else (f" | EXPIROVANY pred {(now - e) / 86400:.0f} dnami - treba autorizovat"
                                                          if e < now else f" | plati este {(e - now) / 86400:.0f} dni")
        print(f"  {name:28} {src[name]}{extra}")
    print(f"\nHOTOVO - vysledok je v schranke. V Render vloz do pola {env} (Ctrl+A, Ctrl+V) a uloz.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
