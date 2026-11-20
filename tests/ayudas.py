"""Ayudas compartidas de los tests (datos inventados)."""
import json

FIRMA = ("Lucas\n\nLucas Pesqueira · Tinko Projects\n"
         "Monseñor Piaggio 55, Avellaneda (1870), Buenos Aires, Argentina · Reply \"no\" and I won't email you again.")


def texto_bien(negocio, precio, tipo):
    """Un borrador que cumple la plantilla (para que pase el control de calidad)."""
    if tipo == "seguimiento 1":
        cuerpo = ("Hi again,\n\nJust making sure this didn't get buried. The replies I wrote for your reviews are "
                  "yours to use either way.\n\nAnd if you'd rather not deal with reviews at all, I can handle every "
                  f"one for ${precio}/month, no contract, cancel anytime.\n\nThanks for your time.")
        cita = "\n\nOn Mon, Nov 30, 2026 10:05 AM, Lucas Pesqueira <lucas@ejemplo-tinko.com>\nwrote:\n\n> Hi there\n> $5000"
        return cuerpo + "\n\n" + FIRMA + cita
    if tipo == "seguimiento 2":
        desc = 29 if precio <= 59 else 49
        cuerpo = (f"Hi {negocio} team,\n\nLast note from me. I'll reply to all your reviews from the last 30 days "
                  f"for free.\n\nIf you like it, it's ${desc}/month for your first 3 months instead of ${precio}, "
                  "in exchange for a short, honest testimonial.\n\nHere's my site if you want to check it out: "
                  "tinkoprojects.com\n\nThanks a lot for your time, and good luck with everything.")
        return cuerpo + "\n\n" + FIRMA + "\n\nOn Tue, Dec 1, 2026 Lucas Pesqueira <lucas@ejemplo-tinko.com> wrote:\n> old"
    return (f"Hi {negocio} team,\n\nMy name is Lucas. I'm based in Argentina and I just started a small business "
            "helping local companies keep up with their Google reviews. None of your 5 most recent reviews have a "
            "reply yet.\n\nTo Ana: \"Hi Ana, thank you for the kind words! See you next time.\"\n\n"
            f"It's ${precio}/month with no contract.\n\nIf it sounds interesting, just reply \"yes\".\n\n"
            "Thanks for your time.\n\n" + FIRMA)


class GmailFalso:
    """Gmail falso: borradores {id: (para, asunto)} o {id: (para, asunto, texto)}.
    Sin texto, arma uno correcto según el registro (REGISTRO lo setea el fixture)."""
    REGISTRO = None

    def __init__(self, borradores=None, bandeja=()):
        self.b = dict(borradores or {})
        self.bandeja = list(bandeja)
        self.mandados = []
        self.leidos = []

    def borradores(self):
        out = {}
        for did, (para, asunto, *_) in self.b.items():
            out.setdefault(para.lower(), []).append((did, asunto))
        return out

    def borrador(self, did):
        para, asunto, *texto = self.b[did]
        if texto:
            return texto[0]
        r = json.loads(self.REGISTRO.read_text()).get(para.lower(), {})
        tipo = (r.get("armado") or {}).get("tipo", "primer mail")
        return texto_bien(r.get("negocio", "X"), int(r.get("precio") or 99), tipo)

    def mandar(self, did):
        assert did in self.b, "mandó un borrador que no existe"
        self.mandados.append(self.b.pop(did)[0])

    def ids_bandeja(self, consulta):
        return [m["id"] for m in self.bandeja]

    def mensaje(self, mid):
        self.leidos.append(mid)
        return next(m for m in self.bandeja if m["id"] == mid)
