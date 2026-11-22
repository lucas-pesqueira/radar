"""Ayudas compartidas de los tests (datos inventados)."""
import json

FIRMA = ("Lucas\n\nLucas Pesqueira · Tinko Projects\n"
         "Monseñor Piaggio 55, Avellaneda (1870), Buenos Aires, Argentina · Reply \"no\" and I won't email you again.")


def texto_bien(negocio, precio, tipo):
    """Un borrador que cumple la plantilla (para que pase el control de calidad). Plantillas del 22/11/2026."""
    if tipo == "seguimiento 1":
        cuerpo = ("Hi again,\n\nDid the replies for Ana and Bob come in handy?\n\nIf someone else takes care of "
                  "your Google profile, could you forward this to them? The offer stands: I'll reply to your "
                  "unanswered reviews from the last 30 days for free, and nothing goes live without your OK.")
        cita = "\n\nOn Mon, Nov 30, 2026 10:05 AM, Lucas Pesqueira <lucas@ejemplo-tinko.com>\nwrote:\n\n> Hi there\n> $5000"
        return cuerpo + "\n\n" + FIRMA + cita
    if tipo == "seguimiento 2":
        desc = 29 if precio <= 59 else 49
        cuerpo = (f"Hi {negocio} team,\n\nLast note from me, I promise.\n\nI'm just getting started (I'm based in "
                  "Buenos Aires and work U.S. hours), so I'm looking for a few local restaurants to work with in "
                  "exchange for honest feedback. If you're one of them, the free month of replies still stands, and "
                  f"after that it's ${desc}/month for your first 3 months instead of ${precio}.\n\nIf now's not the "
                  "right time, no worries, I won't write again. You can see more about me at tinkoprojects.com.\n\n"
                  "Thanks, and good luck with the holidays.")
        return cuerpo + "\n\n" + FIRMA + "\n\nOn Tue, Dec 1, 2026 Lucas Pesqueira <lucas@ejemplo-tinko.com> wrote:\n> old"
    return (f"Hi {negocio} team,\n\nAna's 5-star review from November 16 is still waiting for a reply, and 4 of "
            "your 5 most recent reviews are the same. So I wrote a reply you can copy and paste:\n\n"
            "To Ana: \"Hi Ana, thanks for coming in. Glad the pad thai hit the spot.\"\n\n"
            "It's yours either way, no strings attached.\n\nI'm Lucas, and I write review replies for local "
            "restaurants. If you'd like, I'll reply to all your unanswered reviews from the last 30 days for free, "
            "and you approve each one before it goes live. After that it's "
            f"${precio}/month to keep up with every new review. No contract.\n\n"
            "Want me to do it? Just reply \"yes\".\n\n" + FIRMA)


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
