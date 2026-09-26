"""Minijob in a private household: payout to the nanny and levies (N-12).

Decision 26.09.2026 (Tobi): the nanny is registered via the Haushaltsscheck
(Minijob im Privathaushalt), she is exempt from her own pension contribution
and the family bears the 2 % flat-rate tax. So she receives the full wage and
the Minijob-Zentrale collects the levies from the family, twice a year
(January–June in July, July–December in January of the following year).

Default rates 2026 (share of the wage, paid by the family):
  Krankenversicherung 5 %, Rentenversicherung 5 %, Pauschsteuer 2 %,
  Umlage U1 0,8 %, Umlage U2 0,22 %, Unfallversicherung 1,6 % = 14,62 %.
Rates are settings (in hundredths of a percent) because they change by year;
a closed month keeps the rates it was closed with.

Amounts are rounded half up to full cents per component. The binding amount
is the notice (Beitragsbescheid) of the Minijob-Zentrale, which calculates on
the half-year sum; the half-year view does the same.
"""
import json

LEVIES = [  # key, label, default rate in hundredths of a percent (2026)
    ('kv', 'Krankenversicherung', 500),
    ('rv', 'Rentenversicherung', 500),
    ('tax', 'Pauschsteuer', 200),
    ('u1', 'Umlage U1 (Krankheit)', 80),
    ('u2', 'Umlage U2 (Mutterschaft)', 22),
    ('uv', 'Unfallversicherung', 160),
]
EMPLOYEE_RV = 1360      # 13,6 % own pension share (2026), only without exemption
LIMIT_CENTS = 60300     # Minijob earnings limit per month 2026
DEFAULTS = {'rates': {key: rate for key, _, rate in LEVIES}, 'employee_rv': EMPLOYEE_RV,
            'rv_exempt': True, 'tax_by_employer': True, 'limit_cents': LIMIT_CENTS, 'year': 2026}


def share(cents, rate):
    """Rate in hundredths of a percent; round half up to full cents."""
    return (cents * rate + 5000) // 10000


def settings(conn):
    row = conn.execute("SELECT value FROM metadata WHERE key='nanny_levies'").fetchone()
    stored = json.loads(row[0]) if row else {}
    value = {**DEFAULTS, **stored}
    value['rates'] = {**DEFAULTS['rates'], **stored.get('rates', {})}
    return value


def compute(gross, config):
    """Payout and levies for a wage (all amounts in cents)."""
    levies = [{'key': key, 'label': label, 'rate': config['rates'][key], 'cents': share(gross, config['rates'][key])}
              for key, label, _ in LEVIES]
    deductions = []
    if not config['rv_exempt']:
        deductions.append({'label': 'Eigenanteil Rentenversicherung', 'rate': config['employee_rv'],
                           'cents': share(gross, config['employee_rv'])})
    if not config['tax_by_employer']:
        tax = next(l for l in levies if l['key'] == 'tax')
        deductions.append({'label': 'Pauschsteuer (von der Nanny getragen)', 'rate': tax['rate'], 'cents': tax['cents']})
    withheld = sum(d['cents'] for d in deductions)
    collected = sum(l['cents'] for l in levies) + (deductions[0]['cents'] if not config['rv_exempt'] else 0)
    employer_levies = sum(l['cents'] for l in levies) - (0 if config['tax_by_employer'] else next(l['cents'] for l in levies if l['key'] == 'tax'))
    return {'gross': gross, 'payout': gross - withheld, 'deductions': deductions, 'levies': levies,
            'collected': collected, 'family_total': gross - withheld + collected,
            'employer_levies': employer_levies, 'over_limit': gross > config['limit_cents'],
            'limit_cents': config['limit_cents'], 'rv_exempt': config['rv_exempt'],
            'tax_by_employer': config['tax_by_employer']}


def half_year(month):
    """Months of the half year containing ``month`` and when the Minijob-Zentrale collects."""
    year, number = int(month[:4]), int(month[5:7])
    if number <= 6:
        return [f'{year}-{m:02d}' for m in range(1, 7)], f'im Juli {year}'
    return [f'{year}-{m:02d}' for m in range(7, 13)], f'im Januar {year + 1}'
