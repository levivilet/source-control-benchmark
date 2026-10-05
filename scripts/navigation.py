"""Send LVCE's source-control shortcut only after its sidebar is mounted."""
import time


LVCE_READY = """(() => {
  const sidebar = document.querySelector('.SideBar');
  const content = sidebar?.querySelector('.Explorer [role="tree"], .SourceControl textarea');
  const activity = document.querySelector('.ActivityBarItem[title="Source Control"]');
  return !!sidebar?.offsetHeight && !!content?.offsetHeight && !!activity?.offsetHeight;
})()"""


def focus_lvce_source_control(page, process, deadline):
    # Git initialization precedes sidebar mounting. An early shortcut can update
    # layout's selected view while startup is still loading Explorer.
    while not page.evaluate(LVCE_READY):
        if process.poll() is not None:
            raise RuntimeError('LVCE exited before sidebar readiness')
        if time.monotonic() >= deadline:
            raise TimeoutError('LVCE sidebar did not become ready')
        time.sleep(.25)
    page.call('Page.bringToFront')
    page.key('g', 'KeyG', 10)
