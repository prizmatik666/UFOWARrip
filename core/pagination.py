# UFOWARrip
# Created by Prizmatik
# https://github.com/prizmatik666/UFOWARrip


def page_number_exists(page, target):
    return page.evaluate(
        """
        (target) => [...document.querySelectorAll('button.pagination-button')]
          .some(b => (b.innerText || '').trim() === String(target) &&
                     !b.disabled &&
                     b.getAttribute('aria-disabled') !== 'true')
        """,
        target,
    )


def confirm_continue_past_max(cfg, next_page):
    print(
        f"[!] Max pages setting is {cfg.max_pages}, "
        f"but page {next_page} is still available to scan."
    )
    choice = input("Continue scanning? [Y/n] ").strip().lower()
    return choice in {"", "y", "yes"}


def maybe_extend_scan_limit(cfg, page, page_num, next_page, scan_limit):
    if page_num < scan_limit or not page_number_exists(page, next_page):
        return scan_limit, True

    if not confirm_continue_past_max(cfg, next_page):
        print("[WarRip] Stopped at configured max pages.")
        return scan_limit, False

    scan_limit += cfg.max_pages
    print(f"[WarRip] Continuing scan. Temporary scan limit is now {scan_limit} pages.")
    return scan_limit, True
