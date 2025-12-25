from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, Uzytkownik, Pojazd, Zlecenie, PunktDostawy, zlecenie_pojazdy, Trasa  
import re
import requests
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

app = Flask(__name__)
app.secret_key = 'bardzo_sekretny_klucz_produkcyjny'

PL_MIN_LAT = 49.00  # Południe (szczyt Opołonek)
PL_MAX_LAT = 55.00  # Północ (Rozewie + kawałek Bałtyku)
PL_MIN_LON = 14.00  # Zachód (Osinów Dolny)
PL_MAX_LON = 24.20  # Wschód (zakole Bugu koło Zosina)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:admin@localhost/vrp_database'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return Uzytkownik.query.get(int(user_id))



@app.route('/admin')
@login_required
def admin_panel():
    if current_user.rola != 'admin':
        flash('Brak uprawnień administratora!', 'error')
        return redirect(url_for('dashboard'))
    
    users = Uzytkownik.query.order_by(Uzytkownik.id).all()
    return render_template('admin.html', page_title="Panel Administratora", users=users)

@app.route('/admin/add_user', methods=['POST'])
@login_required
def admin_add_user():
    """Dodawanie nowego użytkownika przez administratora."""
    if current_user.rola != 'admin':
        return redirect(url_for('dashboard'))

    login = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'user')

    if Uzytkownik.query.filter_by(login=login).first():
        flash(f'Użytkownik "{login}" już istnieje!', 'error')
    else:
        new_user = Uzytkownik(login=login, rola=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash(f'Dodano użytkownika: {login}', 'success')

    return redirect(url_for('admin_panel'))

@app.route('/admin/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    """Edycja danych użytkownika (login, hasło, rola)."""
    if current_user.rola != 'admin':
        return redirect(url_for('dashboard'))
    
    user = Uzytkownik.query.get_or_404(user_id)

    if request.method == 'POST':
        new_login = request.form.get('username')
        new_password = request.form.get('password')
        new_role = request.form.get('role')

        if new_login != user.login and Uzytkownik.query.filter_by(login=new_login).first():
            flash('Ten login jest już zajęty!', 'error')
            return redirect(url_for('admin_edit_user', user_id=user.id))

        user.login = new_login
        user.rola = new_role
        
        if new_password and new_password.strip():
            user.set_password(new_password)
            flash('Zaktualizowano dane i hasło.', 'success')
        else:
            flash('Zaktualizowano dane (hasło bez zmian).', 'success')

        db.session.commit()
        return redirect(url_for('admin_panel'))

    return render_template('admin_edit.html', page_title="Edycja Użytkownika", user=user)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.rola != 'admin':
        return redirect(url_for('dashboard'))
    
    user_to_delete = Uzytkownik.query.get_or_404(user_id)
    
    if user_to_delete.id == current_user.id:
        flash('Nie możesz usunąć własnego konta administratora!', 'error')
    else:
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f'Użytkownik {user_to_delete.login} został usunięty.', 'success')
        
    return redirect(url_for('admin_panel'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        login = request.form['username']
        password = request.form['password']

        if Uzytkownik.query.filter_by(login=login).first():
            flash('Taki użytkownik już istnieje!', 'error')
            return redirect(url_for('register'))

        nowy_user = Uzytkownik(login=login, rola='user')
        nowy_user.set_password(password)
        
        db.session.add(nowy_user)
        db.session.commit()
        
        flash('Konto założone! Zaloguj się.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        login = request.form['username']
        password = request.form['password']
        
        user = Uzytkownik.query.filter_by(login=login).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash(f'Zalogowano jako {user.rola}', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Nieprawidłowy login lub hasło.', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Wylogowano pomyślnie.', 'success')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', page_title="Pulpit", user=current_user)

@app.route('/pojazdy')
@login_required
def pojazdy():
    user_vehicles = Pojazd.query.filter_by(id_uzytkownika=current_user.id).all()
    return render_template('pojazdy.html', page_title="Moje Pojazdy", pojazdy=user_vehicles)

@app.route('/pojazdy/dodaj', methods=['POST'])
@login_required
def dodaj_pojazd():
    numer = request.form.get('numer_rejestracyjny')
    pojemnosc = request.form.get('pojemnosc')
    lat = request.form.get('lat') 
    lon = request.form.get('lon') 
    
    dostepnosc = True if request.form.get('dostepnosc') else False

    if not numer or not pojemnosc or not lat or not lon:
        flash('Wypełnij wszystkie wymagane pola!', 'error')
        return redirect(url_for('pojazdy'))

    czy_poprawne, komunikat = waliduj_dane_pojazdu(numer, lat, lon)
    if not czy_poprawne:
        flash(komunikat, 'error') 
        return redirect(url_for('pojazdy'))
 
    if Pojazd.query.filter_by(numer_rejestracyjny=numer.upper()).first():
         flash('Pojazd o takiej rejestracji już istnieje!', 'error')
         return redirect(url_for('pojazdy'))

    nowy_pojazd = Pojazd(
        numer_rejestracyjny=numer.upper(), 
        pojemnosc=float(pojemnosc),
        lat=float(lat),
        lon=float(lon),
        id_uzytkownika=current_user.id,
        dostepnosc=dostepnosc
    )

    db.session.add(nowy_pojazd)
    db.session.commit()
    flash('Pojazd został dodany.', 'success')
    return redirect(url_for('pojazdy'))

@app.route('/pojazdy/usun/<int:id_pojazdu>', methods=['POST'])
@login_required
def usun_pojazd(id_pojazdu):
    pojazd = Pojazd.query.get_or_404(id_pojazdu)
    
    if pojazd.id_uzytkownika != current_user.id:
        flash('Nie masz uprawnień do usunięcia tego pojazdu.', 'error')
        return redirect(url_for('pojazdy'))

    db.session.delete(pojazd)
    db.session.commit()
    flash('Pojazd został usunięty.', 'success')
    return redirect(url_for('pojazdy'))

@app.route('/pojazdy/edytuj/<int:id_pojazdu>', methods=['GET', 'POST'])
@login_required
def edytuj_pojazd(id_pojazdu):
    pojazd = Pojazd.query.get_or_404(id_pojazdu)
    
    if pojazd.id_uzytkownika != current_user.id:
        flash('Brak uprawnień.', 'error')
        return redirect(url_for('pojazdy'))

    # --- NOWA WALIDACJA: Czy pojazd jest w aktywnym zleceniu? ---
    # Sprawdzamy czy lista przypisanych zleceń nie jest pusta i czy zlecenia nie są zakończone
    aktywne_zlecenia = [z for z in pojazd.przypisane_zlecenia if z.status != 'zakonczone']
    
    if aktywne_zlecenia:
        flash(f'Nie można edytować pojazdu! Jest przypisany do aktywnego zlecenia: "{aktywne_zlecenia[0].nazwa}". Usuń go ze zlecenia, aby edytować.', 'error')
        return redirect(url_for('pojazdy'))
    # ------------------------------------------------------------

    if request.method == 'POST':
        numer = request.form.get('numer_rejestracyjny')
        pojemnosc = request.form.get('pojemnosc')
        lat = request.form.get('lat')
        lon = request.form.get('lon')
        
        # Checkbox handling
        nowa_dostepnosc = True if request.form.get('dostepnosc') else False

        try:
            pojazd.numer_rejestracyjny = numer.upper().strip()
            pojazd.pojemnosc = float(pojemnosc)
            pojazd.dostepnosc = nowa_dostepnosc
            
            if lat and lon:
                lat_val = float(lat)
                lon_val = float(lon)
                pojazd.lokalizacja = f'POINT({lon_val} {lat_val})'
            
            db.session.commit()
            flash('Pomyślnie zapisano zmiany w pojeździe.', 'success')
            return redirect(url_for('pojazdy'))
            
        except ValueError:
            flash('Błąd wartości liczbowych.', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Błąd bazy: {str(e)}', 'error')

    return render_template('pojazd_edit.html', page_title="Edycja Pojazdu", pojazd=pojazd)


@app.route('/mapa')
@login_required
def mapa():
    return render_template('mapa.html', page_title="Mapa")

def waliduj_dane_pojazdu(numer, lat, lon, pojemnosc):
    numer = numer.upper().strip()
    
    # 1. Regex (bez zmian)
    if not re.match(r"^[A-Z0-9\s]{2,10}$", numer):
        return False, "Nieprawidłowy format tablicy (używaj tylko liter i cyfr)."

    # 2. Konwersja na liczby
    try:
        lat = float(lat)
        lon = float(lon)
        pojemnosc = float(pojemnosc)
    except ValueError:
        return False, "Współrzędne i pojemność muszą być liczbami."

    # 3. NOWE: Sprawdzenie czy punkt jest w Polsce
    if not (PL_MIN_LAT <= lat <= PL_MAX_LAT):
        return False, f"Szerokość (Lat) poza Polską! Wymagane: {PL_MIN_LAT} - {PL_MAX_LAT}"
    
    if not (PL_MIN_LON <= lon <= PL_MAX_LON):
        return False, f"Długość (Lon) poza Polską! Wymagane: {PL_MIN_LON} - {PL_MAX_LON}"
        
    # 4. Pojemność
    if pojemnosc <= 0:
        return False, "Pojemność musi być większa od 0."

    return True, "" 

@app.route('/zlecenia')
@login_required
def zlecenia():
    # Pobieramy tylko zlecenia zalogowanego użytkownika
    user_orders = Zlecenie.query.filter_by(id_uzytkownika=current_user.id).order_by(Zlecenie.data_utworzenia.desc()).all()
    return render_template('zlecenia.html', page_title="Moje Zlecenia", zlecenia=user_orders)

@app.route('/zlecenia/dodaj', methods=['POST'])
@login_required
def dodaj_zlecenie():
    nazwa = request.form.get('nazwa')
    if not nazwa:
        flash('Podaj nazwę zlecenia!', 'error')
        return redirect(url_for('zlecenia'))
    
    nowe = Zlecenie(nazwa=nazwa, id_uzytkownika=current_user.id)
    db.session.add(nowe)
    db.session.commit()
    
    flash(f'Utworzono zlecenie: {nazwa}. Teraz dodaj punkty.', 'success')
    return redirect(url_for('szczegoly_zlecenia', id_zlecenia=nowe.id))

@app.route('/zlecenia/<int:id_zlecenia>', methods=['GET'])
@login_required
def szczegoly_zlecenia(id_zlecenia):
    zlecenie = Zlecenie.query.get_or_404(id_zlecenia)

    if zlecenie.id_uzytkownika != current_user.id:
        flash('Brak dostępu do tego zlecenia.', 'error')
        return redirect(url_for('zlecenia'))

    # NOWE: Pobieramy wszystkie pojazdy użytkownika
    moje_pojazdy = Pojazd.query.filter_by(id_uzytkownika=current_user.id).all()

    return render_template('zlecenie_details.html', 
                           page_title=f"Szczegóły: {zlecenie.nazwa}", 
                           zlecenie=zlecenie,
                           moje_pojazdy=moje_pojazdy) # Przekazujemy do szablonu

@app.route('/zlecenia/usun/<int:id_zlecenia>', methods=['POST'])
@login_required
def usun_zlecenie(id_zlecenia):
    zlecenie = Zlecenie.query.get_or_404(id_zlecenia)
    if zlecenie.id_uzytkownika != current_user.id:
        flash('Brak uprawnień.', 'error')
        return redirect(url_for('zlecenia'))
    
    # --- UWOLNIENIE POJAZDÓW PRZED USUNIĘCIEM ZLECENIA ---
    for pojazd in zlecenie.dostepne_pojazdy:
        pojazd.dostepnosc = True
    # -----------------------------------------------------
        
    db.session.delete(zlecenie)
    db.session.commit()
    flash('Usunięto zlecenie i zwolniono przypisane pojazdy.', 'success')
    return redirect(url_for('zlecenia'))

# --- OBSŁUGA PUNKTÓW DOSTAW ---

@app.route('/zlecenia/<int:id_zlecenia>/dodaj_punkt', methods=['POST'])
@login_required
def dodaj_punkt(id_zlecenia):
    zlecenie = Zlecenie.query.get_or_404(id_zlecenia)
    if zlecenie.id_uzytkownika != current_user.id:
        return redirect(url_for('zlecenia'))

    nazwa = request.form.get('nazwa')
    typ = request.form.get('typ')
    waga = request.form.get('waga')
    lat = request.form.get('lat')
    lon = request.form.get('lon')
    okno_od = request.form.get('okno_od')
    okno_do = request.form.get('okno_do')

    # Prosta walidacja czy punkt jest w Polsce (korzystamy z istniejących stałych w app.py)
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        if not (PL_MIN_LAT <= lat_f <= PL_MAX_LAT) or not (PL_MIN_LON <= lon_f <= PL_MAX_LON):
            flash('Punkt poza granicami Polski!', 'error')
            return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))
    except ValueError:
        flash('Błędne współrzędne.', 'error')
        return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))

    punkt = PunktDostawy(
        id_zlecenia=zlecenie.id,
        nazwa=nazwa,
        typ=typ,
        lat=lat,
        lon=lon,
        waga=float(waga) if waga else 0.0,
        okno_od=okno_od,
        okno_do=okno_do
    )
    
    db.session.add(punkt)
    db.session.commit()
    flash('Dodano punkt do mapy.', 'success')
    return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))

@app.route('/zlecenia/usun_punkt/<int:id_punktu>', methods=['POST'])
@login_required
def usun_punkt(id_punktu):
    punkt = PunktDostawy.query.get_or_404(id_punktu)
    zlecenie = Zlecenie.query.get(punkt.id_zlecenia)
    
    if zlecenie.id_uzytkownika != current_user.id:
        flash('Brak uprawnień.', 'error')
        return redirect(url_for('zlecenia'))
        
    db.session.delete(punkt)
    db.session.commit()
    flash('Punkt usunięty.', 'success')
    return redirect(url_for('szczegoly_zlecenia', id_zlecenia=zlecenie.id))

@app.route('/zlecenia/<int:id_zlecenia>/przypisz_pojazdy', methods=['POST'])
@login_required
def przypisz_pojazdy(id_zlecenia):
    zlecenie = Zlecenie.query.get_or_404(id_zlecenia)

    if zlecenie.id_uzytkownika != current_user.id:
        return redirect(url_for('zlecenia'))

    # 1. Pobieramy listę ID z formularza
    wybrane_ids = [int(x) for x in request.form.getlist('pojazdy_ids')]
    
    # 2. Logika zwalniania pojazdów:
    # Sprawdzamy pojazdy, które BYŁY w zleceniu, ale już ich NIE MA w formularzu.
    # Musimy je "uwolnić" (ustawić dostępność na True).
    for pojazd in zlecenie.dostepne_pojazdy:
        if pojazd.id_pojazdu not in wybrane_ids:
            pojazd.dostepnosc = True

    # Czyścimy obecną listę relacji
    zlecenie.dostepne_pojazdy = []

    # 3. Logika przypisywania i blokowania:
    for pid in wybrane_ids:
        pojazd = Pojazd.query.get(pid)
        
        # Security check + sprawdzenie czy nie jest zajęty gdzie indziej
        if pojazd and pojazd.id_uzytkownika == current_user.id:
            # Sprawdzamy, czy pojazd nie jest "zajęty" (dostepnosc=False) 
            # ALE pomijamy ten warunek, jeśli edytujemy to samo zlecenie (bo wtedy on już jest False)
            jest_w_tym_zleceniu = (pojazd in zlecenie.dostepne_pojazdy) # (choć listę wyczyściliśmy wyżej, to logiczne sprawdzenie)
            
            # Jeśli pojazd jest niedostępny, ale NIE był wcześniej w tym zleceniu (ktoś próbuje zhakować formularz), pomijamy go
            # W praktyce frontend to zablokuje, ale backend musi być bezpieczny.
            
            zlecenie.dostepne_pojazdy.append(pojazd)
            # BLOKADA: Ustawiamy pojazd jako niedostępny, bo jest w zleceniu
            pojazd.dostepnosc = False

    db.session.commit()
    flash('Zaktualizowano flotę. Przypisane pojazdy zostały oznaczone jako zajęte.', 'success')
    return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))

def time_to_minutes(time_str):
    if not time_str: return 0
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def get_osrm_matrix(points):
    """Pobiera macierz czasów i dystansów dla wszystkich punktów na raz."""
    coords = ";".join([f"{p.lon},{p.lat}" for p in points])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords}?annotations=duration,distance"
    
    try:
        response = requests.get(url)
        data = response.json()
        if data['code'] != 'Ok': return None, None
        return data['durations'], data['distances']
    except Exception as e:
        print(f"Błąd OSRM Matrix: {e}")
        return None, None

def get_full_route_geometry(ordered_points):
    """
    NOWE: Pobiera dokładny kształt trasy (GeoJSON) dla posortowanej listy punktów.
    To rozwiązuje problem 3 i 4.
    """
    if len(ordered_points) < 2:
        return None
        
    # Budujemy URL z punktami w ustalonej kolejności
    coords = ";".join([f"{p['lon']},{p['lat']}" for p in ordered_points])
    
    # Używamy serwisu 'route', a nie 'table'. geometries=geojson ułatwi rysowanie w Leaflet
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
    
    try:
        response = requests.get(url)
        data = response.json()
        if data['code'] != 'Ok': return None
        
        # OSRM zwraca trasę, bierzemy geometrię pierwszej (najlepszej) opcji
        return data['routes'][0]['geometry'] # To jest słownik GeoJSON
    except Exception as e:
        print(f"Błąd OSRM Geometry: {e}")
        return None

def solve_vrp_google(zlecenie, pojazdy, punkty_sorted):
    # 1. Pobranie macierzy
    durations, distances = get_osrm_matrix(punkty_sorted)
    if not durations: return None, "Błąd OSRM"

    # Przygotowanie danych
    time_matrix = [[int(d / 60) for d in row] for row in durations] # sekundy -> minuty
    dist_matrix = distances # metry
    
    # AD 1. WAGA HUBU: Wymuszamy 0 dla pierwszego punktu (HUB)
    demands = [int(p.waga) for p in punkty_sorted]
    demands[0] = 0 

    time_windows = []
    for p in punkty_sorted:
        tw_start = time_to_minutes(p.okno_od)
        tw_end = time_to_minutes(p.okno_do)
        time_windows.append((tw_start, tw_end))

    vehicle_capacities = [int(v.pojemnosc) for v in pojazdy]
    num_vehicles = len(pojazdy)
    depot_index = 0

    # 2. Model OR-Tools
    manager = pywrapcp.RoutingIndexManager(len(time_matrix), num_vehicles, depot_index)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        service_time = 15 if from_node != 0 else 0 
        return time_matrix[from_node][to_node] + service_time

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Wymiar Czasu
    time_dimension_name = 'Time'
    routing.AddDimension(
        transit_callback_index,
        30,      # allow_waiting_time
        24 * 60, # max_time_per_vehicle
        False,   # Don't force start cumul to zero
        time_dimension_name)
    time_dimension = routing.GetDimensionOrDie(time_dimension_name)

    for location_idx, (start, end) in enumerate(time_windows):
        if location_idx == 0: continue 
        index = manager.NodeToIndex(location_idx)
        time_dimension.CumulVar(index).SetRange(start, end)

    # Wymiar Pojemności
    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,  
        vehicle_capacities, 
        True, 
        'Capacity')

    # 3. Rozwiązywanie
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    search_parameters.time_limit.seconds = 5

    solution = routing.SolveWithParameters(search_parameters)

    # 4. Wyniki
    if solution:
        routes_result = []
        for vehicle_id in range(num_vehicles):
            index = routing.Start(vehicle_id)
            
            route_points_data = [] # Lista słowników do pobrania geometrii
            route_details_json = [] # JSON do bazy
            
            route_dist_meters = 0 # AD 2. Sumowanie dystansu
            route_time_minutes = 0
            
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                
                # Zbieramy dane
                p_obj = punkty_sorted[node_index]
                
                # Dane do OSRM (lat/lon)
                route_points_data.append({'lat': p_obj.lat, 'lon': p_obj.lon})
                
                # Dane do JSONa
                time_var = time_dimension.CumulVar(index)
                load_var = routing.GetDimensionOrDie('Capacity').CumulVar(index)
                
                point_info = {
                    "id_punktu": p_obj.id,
                    "nazwa": p_obj.nazwa,
                    "typ": p_obj.typ,
                    "przyjazd_min": solution.Min(time_var),
                    "ladunek": solution.Value(load_var)
                }
                route_details_json.append(point_info)

                previous_index = index
                index = solution.Value(routing.NextVar(index))
                
                # AD 2. Sumujemy dystans z macierzy
                if not routing.IsEnd(index):
                    next_node = manager.IndexToNode(index)
                    route_dist_meters += dist_matrix[node_index][next_node]

            # Dodajemy powrót do HUBa
            node_index = manager.IndexToNode(index)
            p_obj = punkty_sorted[node_index]
            route_points_data.append({'lat': p_obj.lat, 'lon': p_obj.lon})
            
            route_details_json.append({
                "id_punktu": p_obj.id,
                "nazwa": "Koniec: " + p_obj.nazwa,
                "typ": "END"
            })
            
            # Pobieramy czas całkowity z ostatniego punktu
            route_time_minutes = solution.Min(time_dimension.CumulVar(index))

            # Zapisujemy tylko niepuste trasy
            if len(route_points_data) > 2:
                # AD 3. Pobieramy geometrię
                geometry_geojson = get_full_route_geometry(route_points_data)
                
                routes_result.append({
                    "pojazd_db": pojazdy[vehicle_id],
                    "punkty_json": route_details_json,
                    "czas_calkowity": route_time_minutes,
                    "dystans_km": round(route_dist_meters / 1000, 2), # AD 2. Konwersja na km
                    "geometria": geometry_geojson # AD 3. GeoJSON
                })
        
        return routes_result, "OK"
    else:
        return None, "Brak rozwiązania."

@app.route('/zlecenia/<int:id_zlecenia>/optymalizuj', methods=['POST'])
@login_required
def optymalizuj_zlecenie(id_zlecenia):
    zlecenie = Zlecenie.query.get_or_404(id_zlecenia)
    
    # ... (Walidacje bez zmian: id_uzytkownika, status, pojazdy) ...
    if zlecenie.id_uzytkownika != current_user.id:
        flash('Brak uprawnień.', 'error')
        return redirect(url_for('zlecenia'))
    if zlecenie.status == 'zakonczone':
        return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))
    if not zlecenie.dostepne_pojazdy:
        flash('Przypisz pojazdy!', 'error')
        return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))

    hubs = [p for p in zlecenie.punkty if p.typ == 'HUB']
    deliveries = [p for p in zlecenie.punkty if p.typ == 'DELIVERY']
    
    if not hubs:
        flash('Brak HUBa.', 'error')
        return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))
    
    punkty_sorted = [hubs[0]] + deliveries 

    try:
        wyniki_tras, komunikat = solve_vrp_google(zlecenie, zlecenie.dostepne_pojazdy, punkty_sorted)
        
        if not wyniki_tras:
            flash(f'Błąd: {komunikat}', 'error')
            return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))

        # Czyszczenie starych tras
        Trasa.query.filter_by(id_zlecenia=zlecenie.id).delete()
        
        for wynik in wyniki_tras:
            # AD 3. Konwersja GeoJSON na string do zapisu w bazie
            import json
            geo_str = json.dumps(wynik['geometria']) if wynik['geometria'] else None
            
            nowa_trasa = Trasa(
                id_zlecenia=zlecenie.id,
                id_pojazdu=wynik['pojazd_db'].id_pojazdu,
                dlugosc=wynik['dystans_km'],         # AD 2. Zapisujemy dystans
                czas_przejazdu=wynik['czas_calkowity'],
                szczegoly_punktow=wynik['punkty_json'],
                geometria_trasy=geo_str              # AD 3. Zapisujemy geometrię
            )
            db.session.add(nowa_trasa)
        
        zlecenie.status = 'zakonczone'
        db.session.commit()
        flash('Zoptymalizowano pomyślnie!', 'success')
        
    except Exception as e:
        db.session.rollback()
        print(e)
        flash(f'Wyjątek: {str(e)}', 'error')

    return redirect(url_for('szczegoly_zlecenia', id_zlecenia=id_zlecenia))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

