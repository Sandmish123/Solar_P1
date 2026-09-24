"""Slab (telescopic) electricity tariffs and net-metering settlement.

Pure functions, no DB or IO, like the rest of this package.

Two things make Indian residential billing different from a flat rate, and both change
what solar is worth:

- **Telescopic slabs.** Each band of units is charged at its own rate, so the *marginal*
  unit costs the top band the customer reaches. Solar removes units from the top of the
  bill downwards, so it saves more than `units x average tariff` suggests.
- **Banking.** A month that generates more than it consumes does not get paid for the
  surplus; the units bank as credit and offset a later month. Only the balance left at
  the end of the settlement year is bought out, at a regulated rate far below retail.

No tariff rates are shipped. They vary by DISCOM, category and revision, and a stale
rate in a customer proposal is a commercial problem; the operator enters their own.
"""

SETTLEMENT_MONTHS = 12


def validate_slabs(slabs: list) -> list:
    """Normalised slabs, or ValueError. Each is {"upto": units|None, "rate": inr}, in
    ascending order, and only the last may be open-ended."""
    if not slabs:
        raise ValueError("a tariff needs at least one slab")

    normalised = []
    previous_upto = 0.0
    for index, slab in enumerate(slabs):
        try:
            rate = float(slab["rate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"slab {index + 1} has no usable rate")
        if rate < 0:
            raise ValueError(f"slab {index + 1} has a negative rate")

        upto = slab.get("upto")
        is_last = index == len(slabs) - 1
        if upto is None:
            if not is_last:
                raise ValueError("only the final slab may be open-ended")
        else:
            upto = float(upto)
            if upto <= previous_upto:
                raise ValueError("slab boundaries must increase")
            previous_upto = upto

        normalised.append({"upto": upto, "rate": rate})

    if normalised[-1]["upto"] is not None:
        raise ValueError("the final slab must be open-ended, or consumption above it cannot be billed")
    return normalised


def slab_bill(units: float, slabs: list, escalation_factor: float = 1.0) -> float:
    """Energy charge for `units` in one month. Fixed charges are deliberately excluded:
    they do not change when solar is added, so they cancel out of any saving."""
    if units <= 0:
        return 0.0

    total = 0.0
    band_start = 0.0
    for slab in slabs:
        band_end = slab["upto"] if slab["upto"] is not None else units
        if units <= band_start:
            break
        billed = min(units, band_end) - band_start
        total += billed * slab["rate"] * escalation_factor
        band_start = band_end
    return total


def marginal_rate(units: float, slabs: list, escalation_factor: float = 1.0) -> float:
    """Rate the next unit would cost: what a solar unit actually displaces."""
    band_start = 0.0
    for slab in slabs:
        if slab["upto"] is None or units < slab["upto"]:
            return slab["rate"] * escalation_factor
        band_start = slab["upto"]
    return slabs[-1]["rate"] * escalation_factor


def settle_net_metering(monthly_generation: list, monthly_consumption: list) -> dict:
    """One settlement year of net metering.

    Surplus banks as credit and offsets later months; whatever is still banked at the
    end of the year is the only part bought out at the export rate. Generation is
    conserved: self-consumed + banked surplus equals total generation.
    """
    if len(monthly_generation) != SETTLEMENT_MONTHS or len(monthly_consumption) != SETTLEMENT_MONTHS:
        raise ValueError(f"both series must have {SETTLEMENT_MONTHS} months")

    credit = 0.0
    self_consumed = 0.0
    monthly_imports = []

    for generated, consumed in zip(monthly_generation, monthly_consumption):
        available = generated + credit
        offset = min(available, consumed)
        self_consumed += offset
        credit = available - offset
        monthly_imports.append(max(0.0, consumed - available))

    return {
        "monthly_imports": monthly_imports,
        "self_consumed_kwh": self_consumed,
        "banked_surplus_kwh": credit,
    }
