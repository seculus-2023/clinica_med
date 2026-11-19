"""PIX "copia e cola" (BR Code estático, padrão EMV do Banco Central) com valor e identificador."""
import unicodedata


def _campo(id_, valor):
    return f'{id_}{len(valor):02d}{valor}'


def _limpo(txt, n):
    txt = unicodedata.normalize('NFKD', txt or '').encode('ascii', 'ignore').decode().upper()
    return ''.join(c for c in txt if c.isalnum() or c == ' ')[:n].strip() or 'NA'


def _crc16(payload):
    crc = 0xFFFF
    for b in payload.encode('utf-8'):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f'{crc:04X}'


def br_code(chave, nome, cidade, valor=None, txid='***', descricao=''):
    conta = _campo('00', 'br.gov.bcb.pix') + _campo('01', chave.strip())
    if descricao:
        conta += _campo('02', _limpo(descricao, 40))
    payload = (_campo('00', '01') + _campo('26', conta) + _campo('52', '0000') + _campo('53', '986') +
               (_campo('54', f'{valor:.2f}') if valor else '') + _campo('58', 'BR') + _campo('59', _limpo(nome, 25)) +
               _campo('60', _limpo(cidade, 15)) +
               _campo('62', _campo('05', ''.join(c for c in (txid or '***') if c.isalnum())[:25] or '***')) + '6304')
    return payload + _crc16(payload)
