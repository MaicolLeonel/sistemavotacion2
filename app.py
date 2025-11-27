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
    # Aceptar Excel y CSV
    if file.filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file, dtype=str)
    elif file.filename.endswith(".csv"):
        df = pd.read_csv(file, dtype=str)
    else:
        return None, "Formato no soportado (solo Excel o CSV)."

    # Normalizar columnas
    df.columns = (
        df.columns.str.lower()
        .str.strip()
        .str.replace(" ", "")
        .str.replace("_", "")
    )

    # Detectar columnas
    col_apellido = next((c for c in df.columns if "apellido" in c), None)
    col_nombre = next((c for c in df.columns if "nombre" in c), None)
    col_dni = next((c for c in df.columns if "dni" in c), None)

    # Manejar caso donde apellido y nombre están juntos
    if not col_apellido and not col_nombre:
        # Tomar primera columna como nombre completo
        col_nombre_completo = df.columns[0]
        df["apellido_nombre"] = df[col_nombre_completo].astype(str)
    else:
        # Crear columna combinada
        apellido = df[col_apellido].astype(str) if col_apellido else ""
        nombre = df[col_nombre].astype(str) if col_nombre else ""
        df["apellido_nombre"] = (apellido + " " + nombre).str.strip()

    # Verificar DNI
    if not col_dni:
        return None, f"No se encontró columna de DNI. Columnas detectadas: {list(df.columns)}"

    # Crear dataframe limpio
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

    socios = get_socios(user)
    total = len(socios)
    votaron = len([s for s in socios if s[3] == 1])
    restan = total - votaron

    return render_template(
        "index.html",
        socios=socios,
        total=total,
        votaron=votaron,
        restan=restan,
        user=user
    )


@app.route("/panel/<user>/votar/<int:socio_id>")
def votar(user, socio_id):
    if user not in USERS:
        return "Usuario no válido"

    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("UPDATE socios SET voto=1 WHERE id=?", (socio_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("panel", user=user))


@app.route("/panel/<user>/borrar/<int:socio_id>")
def borrar(user, socio_id):
    if user not in USERS:
        return "Usuario no válido"

    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM socios WHERE id=?", (socio_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("panel", user=user))


@app.route("/panel/<user>/agregar", methods=["POST"])
def agregar(user):
    if user not in USERS:
        return "Usuario no válido"

    apellido = request.form.get("apellido", "").strip()
    nombre = request.form.get("nombre", "").strip()
    dni = request.form.get("dni", "").strip()

    if not (apellido and nombre and dni):
        return redirect(url_for("panel", user=user))

    nombre_final = f"{apellido} {nombre}"

    db = get_db_path(user)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO socios (nombre, dni) VALUES (?, ?)",
        (nombre_final, dni)
    )
    conn.commit()
    conn.close()

    return redirect(url_for("panel", user=user))


@app.route("/panel/<user>/descargar")
def descargar(user):
    if user not in USERS:
        return "Usuario no válido"

    socios = get_socios(user)
    df = pd.DataFrame(socios, columns=["ID", "Nombre", "DNI", "Voto"])

    # Reemplazar 1/0 por texto
    df["Voto"] = df["Voto"].map({1: "VOTÓ", 0: "NO VOTÓ"})

    # Calcular totales
    total = len(df)
    votaron = (df["Voto"] == "VOTÓ").sum()
    restan = total - votaron

    # Crear un Excel en memoria
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Hoja principal
        df.to_excel(writer, index=False, sheet_name=f"Padron_{user}")

        # Hoja con totales AL FINAL
        summary = pd.DataFrame({
            "Descripción": ["Total de socios", "Votaron", "Faltan"],
            "Cantidad": [total, votaron, restan]
        })

        summary.to_excel(
            writer,
            index=False,
            sheet_name=f"Padron_{user}",
            startrow=len(df) + 2  # 2 filas en blanco después de la tabla
        )

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"padron_{user}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )



if __name__ == "__main__":
    app.run(debug=True)
