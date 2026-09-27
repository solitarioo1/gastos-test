"""Crea o actualiza tu usuario para entrar a TusGastos.

Uso:
    python crear_usuario.py

Pide el usuario y la clave por teclado; la clave no se muestra en pantalla
y se guarda en Postgres como hash (nunca en texto plano).
"""
import getpass

from dotenv import load_dotenv

import usuarios_pg

load_dotenv()


def main():
    usuario = input("Usuario: ").strip()
    clave = getpass.getpass("Clave: ")
    if clave != getpass.getpass("Repite la clave: "):
        print("Las claves no coinciden. Nada se guardó.")
        return
    usuarios_pg.crear_usuario(usuario, clave)
    print(f"Listo: '{usuario}' ya puede entrar a TusGastos.")


if __name__ == "__main__":
    main()
