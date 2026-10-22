"""Discovery batch split: seed keywords vs exploration queries (Stage 6)."""


def split_discovery_batch_slots(
    batch_size: int,
    *,
    exploration_enabled: bool,
    exploration_fraction: float,
) -> tuple[int, int]:
    """
    Return (seed_slots, exploration_slots) summing to batch_size.

    When exploration is enabled and batch_size >= 2: at least one seed slot and at least one
    exploration slot (exploration does not starve on small batches; seeds are not displaced).
    batch_size == 1: exploration gets 0 (only seeds).
    """
    total = max(0, int(batch_size))
    if total == 0 or not exploration_enabled:
        return total, 0
    if total == 1:
        return 1, 0

    fraction = min(1.0, max(0.0, float(exploration_fraction)))
    if fraction <= 0:
        return total, 0

    exploration_slots = int(total * fraction)
    if exploration_slots < 1:
        exploration_slots = 1
    if exploration_slots > total - 1:
        exploration_slots = total - 1
    seed_slots = total - exploration_slots
    return seed_slots, exploration_slots
