from flask import Flask, render_template, request, redirect, url_for, send_file
import sqlite3
import pandas as pd
import io

app = Flask(__name__)

USERS = ["usuario1", "usuario2", "usuario3", "usuario4", "usuario5"]


def get_db_path(user: str) -> str:
    return f"padron_{user}.db"


def init_db(user: str) -> None:
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            dni TEXT,
            voto INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


def get_socios(user: str):
    init_db(user)
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM socios")
    data = cursor.fetchall()
    conn.close()
    return data


def process_file(file):
    # Aceptar Excel o CSV
    if file.filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file, dtype=str)
    elif file.filename.endswith(".csv"):
        df = pd.read_csv(file, dtype=str)
    else:
        return None, "Formato no soportado (solo Excel o CSV)."

    # Normalizar columnas
    df.columns = (
        df.columns.str.lower()
        .str.replace(" ", "")
        .str.replace("_", "")
        .str.strip()
    )

    # Buscar columnas relevantes
    col_apellido = next((c for c in df.columns if "apellido" in c), None)
    col_nombre = next((c for c in df.columns if "nombre" in c), None)
    col_dni = next((c for c in df.columns if "dni" in c), None)

    # Si apellido & nombre no están separados
    if not col_apellido and not col_nombre:
        columna_completa = df.columns[0]
        df["apellido_nombre"] = df[columna_completa].astype(str)
    else:
        apellido = df[col_apellido].astype(str) if col_apellido else ""
        nombre = df[col_nombre].astype(str) if col_nombre else ""
        df["apellido_nombre"] = (apellido + " " + nombre).str.strip()

    if not col_dni:
        return None, f"No se encontró columna DNI. Columnas: {list(df.columns)}"

    df_clean = df[["apellido_nombre", col_dni]].copy()
    df_clean = df_clean.rename(columns={"apellido_nombre": "nombre", col_dni: "dni"})
    df_clean = df_clean.drop_duplicates()

    return df_clean, None


@app.route("/")
def select_user():
    return render_template("select_user.html", users=USERS)


@app.route("/panel/<user>", methods=["GET", "POST"])
def panel(user):
    if user not in USERS:
        return "Usuario no válido"

    init_db(user)

    # Si suben archivo Excel
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            return "No seleccionaste archivo"

        df_clean, error = process_file(file)
        if error:
            return error

        db = get_db_path(user)
        conn = sqlite3.connect(db)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM socios")

        for _, row in df_clean.iterrows():
            cursor.execute(
                "INSERT INTO socios (nombre, dni) VALUES (?, ?)",
                (row["nombre"].strip(), row["dni"].strip())
            )

        conn.commit()
        conn.close()

        return redirect(url_for("panel", user=user))

    # FILTRO DE BÚSQUEDA (SÚPER RÁPIDO)
    buscar = request.args.get("buscar", "").lower().strip()
    todos = get_socios(user)

    if buscar:
        socios = [
            s for s in todos
            if buscar in s[1].lower() or buscar in s[2].lower()
        ]
    else:
        socios = todos

    total = len(todos)
    votaron = len([s for s in todos if s[3] == 1])
    restan = total - votaron

    return render_template(
        "index.html",
        socios=socios,
        total=total,
        votaron=votaron,
        restan=restan,
        user=user,
        buscar=buscar
    )


@app.route("/panel/<user>/votar/<int:socio_id>")
def votar(user, socio_id):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("UPDATE socios SET voto=1 WHERE id=?", (socio_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("panel", user=user))


@app.route("/panel/<user>/borrar/<int:socio_id>")
def borrar(user, socio_id):
    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM socios WHERE id=?", (socio_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("panel", user=user))


@app.route("/panel/<user>/agregar", methods=["POST"])
def agregar(user):
    apellido = request.form.get("apellido", "").strip()
    nombre = request.form.get("nombre", "").strip()
    dni = request.form.get("dni", "").strip()

    if not (apellido and nombre and dni):
        return redirect(url_for("panel", user=user))

    nombre_completo = f"{apellido} {nombre}"

    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO socios (nombre, dni) VALUES (?, ?)",
        (nombre_completo, dni)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("panel", user=user))


@app.route("/panel/<user>/descargar")
def descargar(user):
    socios = get_socios(user)
    df = pd.DataFrame(socios, columns=["ID", "Nombre", "DNI", "Voto"])

    df["Voto"] = df["Voto"].map({1: "VOTÓ", 0: "NO VOTÓ"})

    total = len(df)
    votaron = (df["Voto"] == "VOTÓ").sum()
    restan = total - votaron

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Padrón")

        resumen = pd.DataFrame({
            "Descripción": ["Total socios", "Votaron", "Faltan"],
            "Cantidad": [total, votaron, restan]
        })
        resumen.to_excel(writer, index=False, sheet_name="Padrón", startrow=len(df) + 2)

    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"padron_{user}.xlsx")
    

if __name__ == "__main__":
    app.run(debug=True)
