from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from geoalchemy2 import Geometry
from geoalchemy2.shape import to_shape
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSON
db = SQLAlchemy()

class Uzytkownik(UserMixin, db.Model):
    __tablename__ = 'uzytkownicy'
    id = db.Column(db.Integer, primary_key=True) 
    login = db.Column(db.String(150), unique=True, nullable=False) 
    password_hash = db.Column(db.String(256), nullable=False) 
    rola = db.Column(db.String(50), default='user') 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Pojazd(db.Model):
    __tablename__ = 'pojazdy'

    id_pojazdu = db.Column(db.Integer, primary_key=True)
    numer_rejestracyjny = db.Column(db.String(20), unique=True, nullable=False)
    pojemnosc = db.Column(db.Float, nullable=False)
    dostepnosc = db.Column(db.Boolean, default=True, nullable=False)
    
    lokalizacja = db.Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)
    id_uzytkownika = db.Column(db.Integer, db.ForeignKey('uzytkownicy.id'), nullable=False)

    def __init__(self, numer_rejestracyjny, pojemnosc, lat, lon, id_uzytkownika, dostepnosc=True):
        self.numer_rejestracyjny = numer_rejestracyjny
        self.pojemnosc = pojemnosc
        self.lokalizacja = f'POINT({lon} {lat})'
        self.id_uzytkownika = id_uzytkownika
        self.dostepnosc = dostepnosc

    @property
    def lat(self):
        if isinstance(self.lokalizacja, str):
            try:
                coords = self.lokalizacja.replace('POINT(', '').replace(')', '').split()
                return float(coords[1])
            except:
                return 0.0
        point = to_shape(self.lokalizacja)
        return point.y

    @property
    def lon(self):
        if isinstance(self.lokalizacja, str):
            try:
                coords = self.lokalizacja.replace('POINT(', '').replace(')', '').split()
                return float(coords[0])
            except:
                return 0.0
        point = to_shape(self.lokalizacja)
        return point.x
    
zlecenie_pojazdy = db.Table('zlecenie_pojazdy',
    db.Column('zlecenie_id', db.Integer, db.ForeignKey('zlecenia.id'), primary_key=True),
    db.Column('pojazd_id', db.Integer, db.ForeignKey('pojazdy.id_pojazdu'), primary_key=True)
)


class Zlecenie(db.Model):
    __tablename__ = 'zlecenia'
    
    id = db.Column(db.Integer, primary_key=True)
    nazwa = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='nowe')  
    data_utworzenia = db.Column(db.DateTime, default=datetime.utcnow)
    
    id_uzytkownika = db.Column(db.Integer, db.ForeignKey('uzytkownicy.id'), nullable=False)
    
    punkty = db.relationship('PunktDostawy', backref='zlecenie', lazy=True, cascade='all, delete-orphan')
    dostepne_pojazdy = db.relationship('Pojazd', secondary=zlecenie_pojazdy, lazy='subquery',
        backref=db.backref('przypisane_zlecenia', lazy=True))
    
class PunktDostawy(db.Model):
    __tablename__ = 'punkty_dostaw'
    
    id = db.Column(db.Integer, primary_key=True)
    id_zlecenia = db.Column(db.Integer, db.ForeignKey('zlecenia.id'), nullable=False)
    
    nazwa = db.Column(db.String(100))
    typ = db.Column(db.String(20))
    waga = db.Column(db.Float, default=0.0)
    
    okno_od = db.Column(db.String(5), default="08:00") 
    okno_do = db.Column(db.String(5), default="16:00")

    lokalizacja = db.Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)

    def __init__(self, id_zlecenia, nazwa, typ, lat, lon, waga, okno_od, okno_do):
        self.id_zlecenia = id_zlecenia
        self.nazwa = nazwa
        self.typ = typ
        self.lokalizacja = f'POINT({lon} {lat})'
        self.waga = waga
        self.okno_od = okno_od
        self.okno_do = okno_do

    @property
    def lat(self):
        point = to_shape(self.lokalizacja)
        return point.y

    @property
    def lon(self):
        point = to_shape(self.lokalizacja)
        return point.x

    def to_dict(self):
        return {
            'id': self.id,
            'nazwa': self.nazwa,
            'typ': self.typ,
            'waga': self.waga,
            'lat': self.lat,
            'lon': self.lon,
            'okno_od': self.okno_od,
            'okno_do': self.okno_do
        }
    
class Trasa(db.Model):
    __tablename__ = 'trasy'
    
    id = db.Column(db.Integer, primary_key=True)
    id_zlecenia = db.Column(db.Integer, db.ForeignKey('zlecenia.id'), nullable=False)
    id_pojazdu = db.Column(db.Integer, db.ForeignKey('pojazdy.id_pojazdu'), nullable=False)
    
    dlugosc = db.Column(db.Float)
    czas_przejazdu = db.Column(db.Float)
    data_generacji = db.Column(db.DateTime, default=datetime.utcnow)
    
    geometria_trasy = db.Column(db.Text)
    szczegoly_punktow = db.Column(JSON)
    
    pojazd = db.relationship('Pojazd', backref='realizowane_trasy')
    
    zlecenie = db.relationship('Zlecenie', backref=db.backref('wygenerowane_trasy', cascade='all, delete-orphan'))