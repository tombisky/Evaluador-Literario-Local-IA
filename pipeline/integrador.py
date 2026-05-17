def integrar(
    fragmento_id: str,
    capitulo: int,
    palabra_inicio: int,
    palabra_fin: int,
    escena: dict,
    entidades: list,
    estados: list,
    conflicto: dict,
    tiempo: dict
) -> dict:
    return {
        "fragmento_id": fragmento_id,
        "capitulo": capitulo,
        "palabra_inicio": palabra_inicio,
        "palabra_fin": palabra_fin,
        "escena": escena,
        "entidades": entidades,
        "estados": estados,
        "conflicto": conflicto,
        "tiempo": tiempo
    }
