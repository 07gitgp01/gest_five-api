"""
seed.py - Donnees de demonstration GestFive
Usage :
    python seed.py              # insere tout + upload images Cloudinary
    python seed.py --no-images  # insere tout, garde les URLs Unsplash
    python seed.py --reset      # supprime tout puis reinsere
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv()

# --- Config -------------------------------------------------------------------

DATABASE_URL = os.environ["DATABASE_URL"]
SYNC_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
if not SYNC_URL.startswith("postgresql+psycopg2://"):
    SYNC_URL = SYNC_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

# --- Helpers ------------------------------------------------------------------

def log(msg): print(msg, flush=True)
def uid(): return str(uuid.uuid4())
def now_utc(): return datetime.now(timezone.utc)
def days_ago(n): return now_utc() - timedelta(days=n)
def days_from_now(n): return now_utc() + timedelta(days=n)


def hash_password(plain):
    from argon2 import PasswordHasher
    ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2,
                        hash_len=32, salt_len=16)
    return ph.hash(plain)


def upload_image(url, public_id):
    try:
        result = cloudinary.uploader.upload(
            url,
            public_id=f"gestfive/{public_id}",
            overwrite=True,
            resource_type="image",
            transformation=[{"width": 800, "height": 600,
                             "crop": "fill", "quality": "auto"}],
        )
        return result["secure_url"]
    except Exception as e:
        log(f"  WARN: upload echoue pour {public_id}: {e}")
        return url


# --- Donnees ------------------------------------------------------------------

UNSPLASH = {
    "stadium":  "https://images.unsplash.com/photo-1529900748604-07564a03e7a6?w=800",
    "stadium2": "https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=800",
    "stadium3": "https://images.unsplash.com/photo-1551280857-2b9bbe52acf4?w=800",
    "green":    "https://images.unsplash.com/photo-1543351611-58f69d7c1781?w=800",
    "green2":   "https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b?w=800",
    "bobo":     "https://images.unsplash.com/photo-1518002054494-3a6f94352e9d?w=800",
    "bobo2":    "https://images.unsplash.com/photo-1540747913346-19e32dc3e97e?w=800",
    "city":     "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?w=800",
    "premier":  "https://images.unsplash.com/photo-1560272564-c83b66b1ad12?w=800",
    "premier2": "https://images.unsplash.com/photo-1459865264687-595d652de67e?w=800",
}

OPENING_HOURS = {
    "monday":    {"open": "08:00", "close": "23:00"},
    "tuesday":   {"open": "08:00", "close": "23:00"},
    "wednesday": {"open": "08:00", "close": "23:00"},
    "thursday":  {"open": "08:00", "close": "23:00"},
    "friday":    {"open": "08:00", "close": "00:00"},
    "saturday":  {"open": "07:00", "close": "00:00"},
    "sunday":    {"open": "07:00", "close": "22:00"},
}


# --- Seed ---------------------------------------------------------------------

def run(use_cloudinary=True, reset=False):
    log("=" * 50)
    log("GestFive - Seed donnees demo")
    log("=" * 50)

    engine = create_engine(SYNC_URL, echo=False)

    with Session(engine) as db:

        # Reset
        if reset:
            log("\nReset de la base...")
            db.execute(text("DELETE FROM payments"))
            db.execute(text("DELETE FROM reservations"))
            db.execute(text("DELETE FROM time_slots"))
            db.execute(text("DELETE FROM terrains"))
            db.execute(text(
                "DELETE FROM users WHERE phone IN ("
                "'+22670000001','+22670000002','+22670000003',"
                "'+22670000010','+22670000011')"
            ))
            db.commit()
            log("OK - Reset termine")

        # 1. Images
        log("\n1. Images")
        photos = {}
        if use_cloudinary and os.getenv("CLOUDINARY_CLOUD_NAME", "your_cloud_name") != "your_cloud_name":
            total = len(UNSPLASH)
            for i, (key, url) in enumerate(UNSPLASH.items(), 1):
                log(f"  [{i}/{total}] Cloudinary: {key}...")
                photos[key] = upload_image(url, key)
            log(f"  OK - {len(photos)} images uploadees sur Cloudinary")
        else:
            photos = dict(UNSPLASH)
            log("  Mode sans Cloudinary - URLs Unsplash conservees")

        # 2. Utilisateurs
        log("\n2. Utilisateurs")

        ID_MOUSSA  = uid()
        ID_IBRAHIM = uid()
        ID_ADAMA   = uid()
        ID_JOUEUR  = uid()
        ID_JOUEUR2 = uid()

        pwd = hash_password("Demo1234!")

        users = [
            {"id": ID_MOUSSA,  "firstname": "Moussa",  "lastname": "Kabore",
             "phone": "+22670000001", "email": "moussa.kabore@gestfive.demo",
             "hashed_password": pwd, "role": "OWNER",
             "is_active": True, "is_verified": True},
            {"id": ID_IBRAHIM, "firstname": "Ibrahim", "lastname": "Ouedraogo",
             "phone": "+22670000002", "email": "ibrahim.ouedraogo@gestfive.demo",
             "hashed_password": pwd, "role": "OWNER",
             "is_active": True, "is_verified": True},
            {"id": ID_ADAMA,   "firstname": "Adama",   "lastname": "Traore",
             "phone": "+22670000003", "email": "adama.traore@gestfive.demo",
             "hashed_password": pwd, "role": "OWNER",
             "is_active": True, "is_verified": True},
            {"id": ID_JOUEUR,  "firstname": "Seydou",  "lastname": "Kone",
             "phone": "+22670000010", "email": "demo@gestfive.app",
             "hashed_password": pwd, "role": "CLIENT",
             "is_active": True, "is_verified": True},
            {"id": ID_JOUEUR2, "firstname": "Fatima",  "lastname": "Ouattara",
             "phone": "+22670000011", "email": "fatima@gestfive.demo",
             "hashed_password": pwd, "role": "CLIENT",
             "is_active": True, "is_verified": True},
        ]

        inserted = 0
        for u in users:
            row = db.execute(
                text("SELECT id FROM users WHERE phone = :p"), {"p": u["phone"]}
            ).fetchone()
            if not row:
                db.execute(text("""
                    INSERT INTO users
                      (id, firstname, lastname, phone, email, hashed_password,
                       role, is_active, is_verified, created_at, updated_at)
                    VALUES
                      (:id, :firstname, :lastname, :phone, :email, :hashed_password,
                       :role, :is_active, :is_verified, NOW(), NOW())
                """), u)
                inserted += 1
            else:
                real = str(row[0])
                if u["id"] == ID_MOUSSA:   ID_MOUSSA  = real
                elif u["id"] == ID_IBRAHIM: ID_IBRAHIM = real
                elif u["id"] == ID_ADAMA:   ID_ADAMA   = real
                elif u["id"] == ID_JOUEUR:  ID_JOUEUR  = real
                elif u["id"] == ID_JOUEUR2: ID_JOUEUR2 = real
        db.commit()
        log(f"  OK - {inserted} inseres, {len(users)-inserted} deja presents")

        # 3. Terrains
        log("\n3. Terrains")

        ID_T1 = uid(); ID_T2 = uid(); ID_T3 = uid()
        ID_T4 = uid(); ID_T5 = uid()

        terrains = [
            {"id": ID_T1, "owner_id": ID_MOUSSA,
             "name": "Stadium Five Ouaga",
             "description": "Le terrain Five le plus moderne de Ouagadougou. Surface synthetique FIFA Pro, eclairage LED professionnel, vestiaires premium et buvette.",
             "address": "Avenue Kwame N'Krumah, Secteur 4", "city": "Ouagadougou",
             "latitude": 12.3714, "longitude": -1.5197,
             "photos": [photos["stadium"], photos["stadium2"], photos["stadium3"]],
             "price_per_hour": 25000.0, "capacity": 10,
             "has_parking": True, "has_changing_room": True,
             "has_shower": True, "has_lighting": True,
             "average_rating": 4.8, "status": "ACTIVE"},
            {"id": ID_T2, "owner_id": ID_IBRAHIM,
             "name": "Green Field Five",
             "description": "Terrain Five avec gazon naturel entretenu, ideal pour les matchs en famille ou entre collegues.",
             "address": "Rue du Commerce, Zone du Bois", "city": "Ouagadougou",
             "latitude": 12.3642, "longitude": -1.5283,
             "photos": [photos["green"], photos["green2"]],
             "price_per_hour": 18000.0, "capacity": 10,
             "has_parking": True, "has_changing_room": False,
             "has_shower": False, "has_lighting": True,
             "average_rating": 4.3, "status": "ACTIVE"},
            {"id": ID_T3, "owner_id": ID_ADAMA,
             "name": "Five Arena Bobo",
             "description": "La reference des terrains Five a Bobo-Dioulasso. Infrastructure de qualite internationale avec parking securise.",
             "address": "Boulevard de la Revolution", "city": "Bobo-Dioulasso",
             "latitude": 11.1779, "longitude": -4.2979,
             "photos": [photos["bobo"], photos["bobo2"]],
             "price_per_hour": 20000.0, "capacity": 10,
             "has_parking": True, "has_changing_room": True,
             "has_shower": True, "has_lighting": True,
             "average_rating": 4.6, "status": "ACTIVE"},
            {"id": ID_T4, "owner_id": ID_IBRAHIM,
             "name": "City Five Gounghin",
             "description": "Terrain compact et bien entretenu dans le quartier Gounghin. Prix abordable et ambiance conviviale.",
             "address": "Rue 14.45, Gounghin", "city": "Ouagadougou",
             "latitude": 12.3589, "longitude": -1.5421,
             "photos": [photos["city"]],
             "price_per_hour": 15000.0, "capacity": 10,
             "has_parking": False, "has_changing_room": False,
             "has_shower": False, "has_lighting": False,
             "average_rating": 4.1, "status": "ACTIVE"},
            {"id": ID_T5, "owner_id": ID_MOUSSA,
             "name": "Premier Five Pissy",
             "description": "Terrain Five premium avec surface synthetique derniere generation et systeme d'arrosage automatique.",
             "address": "Avenue de la Chance, Pissy", "city": "Ouagadougou",
             "latitude": 12.3456, "longitude": -1.5543,
             "photos": [photos["premier"], photos["premier2"]],
             "price_per_hour": 22000.0, "capacity": 10,
             "has_parking": True, "has_changing_room": True,
             "has_shower": True, "has_lighting": True,
             "average_rating": 4.7, "status": "ACTIVE"},
        ]

        inserted = 0
        for t in terrains:
            row = db.execute(
                text("SELECT id FROM terrains WHERE name=:n AND city=:c"),
                {"n": t["name"], "c": t["city"]}
            ).fetchone()
            if not row:
                db.execute(text("""
                    INSERT INTO terrains
                      (id, owner_id, name, description, address, city,
                       latitude, longitude, photos, opening_hours,
                       price_per_hour, capacity,
                       has_parking, has_changing_room, has_shower, has_lighting,
                       average_rating, status, created_at, updated_at)
                    VALUES
                      (:id, :owner_id, :name, :description, :address, :city,
                       :latitude, :longitude, :photos, :opening_hours,
                       :price_per_hour, :capacity,
                       :has_parking, :has_changing_room, :has_shower, :has_lighting,
                       :average_rating, :status, NOW(), NOW())
                """), {**t,
                       "photos": json.dumps(t["photos"]),
                       "opening_hours": json.dumps(OPENING_HOURS)})
                inserted += 1
            else:
                real = str(row[0])
                if t["id"] == ID_T1: ID_T1 = real
                elif t["id"] == ID_T2: ID_T2 = real
                elif t["id"] == ID_T3: ID_T3 = real
                elif t["id"] == ID_T4: ID_T4 = real
                elif t["id"] == ID_T5: ID_T5 = real
        db.commit()
        log(f"  OK - {inserted} inseres, {len(terrains)-inserted} deja presents")

        # 4. Reservations + Paiements
        log("\n4. Reservations et paiements")

        def make_slot(terrain_id, player_id, days_offset, hour, dur, price,
                      status, pay_method=None, pay_status=None):
            rid = uid()
            base = days_from_now(days_offset) if days_offset >= 0 else days_ago(-days_offset)
            start = base.replace(hour=hour, minute=0, second=0, microsecond=0)
            end   = start + timedelta(hours=dur)
            total = price * dur
            res = {"id": rid, "terrain_id": terrain_id, "player_id": player_id,
                   "time_slot_id": None, "start_datetime": start, "end_datetime": end,
                   "total_price": total, "status": status, "notes": None}
            pay = None
            if pay_method and pay_status:
                pay = {"id": uid(), "reservation_id": rid,
                       "amount": total, "currency": "XOF",
                       "payment_method": pay_method,
                       "transaction_reference": f"GF-{pay_method[:2]}-{rid[:8].upper()}",
                       "provider_reference": f"PRV-{rid[:6].upper()}",
                       "status": pay_status,
                       "paid_at": start - timedelta(days=1) if pay_status == "SUCCESS" else None,
                       "failure_reason": None, "provider_data": None}
            return res, pay

        slots = [
            make_slot(ID_T1, ID_JOUEUR,   2, 18, 1, 25000, "CONFIRMED",  "ORANGE_MONEY", "SUCCESS"),
            make_slot(ID_T3, ID_JOUEUR,   5, 20, 1, 20000, "PENDING"),
            make_slot(ID_T5, ID_JOUEUR2,  3, 17, 2, 22000, "CONFIRMED",  "MOOV_MONEY",   "SUCCESS"),
            make_slot(ID_T2, ID_JOUEUR,  -7, 17, 1, 18000, "COMPLETED",  "CARD",         "SUCCESS"),
            make_slot(ID_T1, ID_JOUEUR, -14, 19, 2, 25000, "COMPLETED",  "ORANGE_MONEY", "SUCCESS"),
            make_slot(ID_T2, ID_JOUEUR, -21, 16, 1, 18000, "COMPLETED",  "MOOV_MONEY",   "SUCCESS"),
            make_slot(ID_T1, ID_JOUEUR, -30, 18, 2, 25000, "COMPLETED",  "ORANGE_MONEY", "SUCCESS"),
            make_slot(ID_T1, ID_JOUEUR, -38, 20, 1, 25000, "COMPLETED",  "CARD",         "SUCCESS"),
            make_slot(ID_T2, ID_JOUEUR, -75, 10, 1, 18000, "COMPLETED",  "ORANGE_MONEY", "SUCCESS"),
            make_slot(ID_T4, ID_JOUEUR, -90, 17, 2, 15000, "COMPLETED",  "MOOV_MONEY",   "SUCCESS"),
            make_slot(ID_T1, ID_JOUEUR,-115, 19, 1, 25000, "COMPLETED",  "ORANGE_MONEY", "SUCCESS"),
            make_slot(ID_T2, ID_JOUEUR,-150, 15, 1, 18000, "COMPLETED",  "MOOV_MONEY",   "SUCCESS"),
            make_slot(ID_T3, ID_JOUEUR, -45, 14, 1, 20000, "CANCELLED"),
            make_slot(ID_T5, ID_JOUEUR2, -3, 16, 1, 22000, "COMPLETED",  "ORANGE_MONEY", "SUCCESS"),
            make_slot(ID_T3, ID_JOUEUR2,-10, 18, 2, 20000, "COMPLETED",  "MOOV_MONEY",   "SUCCESS"),
        ]

        ins_r = ins_p = 0
        for res, pay in slots:
            exists = db.execute(
                text("SELECT 1 FROM reservations WHERE terrain_id=:t AND player_id=:p AND start_datetime=:s"),
                {"t": res["terrain_id"], "p": res["player_id"], "s": res["start_datetime"]}
            ).fetchone()
            if not exists:
                db.execute(text("""
                    INSERT INTO reservations
                      (id, terrain_id, player_id, time_slot_id,
                       start_datetime, end_datetime, total_price, status, notes,
                       created_at, updated_at)
                    VALUES
                      (:id, :terrain_id, :player_id, :time_slot_id,
                       :start_datetime, :end_datetime, :total_price, :status, :notes,
                       NOW(), NOW())
                """), res)
                ins_r += 1
                if pay:
                    db.execute(text("""
                        INSERT INTO payments
                          (id, reservation_id, amount, currency, payment_method,
                           transaction_reference, provider_reference,
                           status, paid_at, failure_reason, provider_data,
                           created_at, updated_at)
                        VALUES
                          (:id, :reservation_id, :amount, :currency, :payment_method,
                           :transaction_reference, :provider_reference,
                           :status, :paid_at, :failure_reason, :provider_data,
                           NOW(), NOW())
                    """), pay)
                    ins_p += 1
        db.commit()
        log(f"  OK - {ins_r} reservations, {ins_p} paiements inseres")

    log("\n" + "=" * 50)
    log("Seed termine !")
    log("Comptes de demo :")
    log("  Joueur  : demo@gestfive.app / +22670000010 / Demo1234!")
    log("  Owner 1 : +22670000001 (Moussa Kabore) / Demo1234!")
    log("  Owner 2 : +22670000002 (Ibrahim Ouedraogo) / Demo1234!")
    log("  Owner 3 : +22670000003 (Adama Traore) / Demo1234!")
    log("=" * 50)


# --- Entree -------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    try:
        run(use_cloudinary=not args.no_images, reset=args.reset)
    except KeyboardInterrupt:
        print("Interrompu.")
        sys.exit(0)
    except Exception as e:
        print(f"ERREUR: {e}")
        raise
