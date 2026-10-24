from tools.build_site import markdown


def test_markdown_subset():
    out = markdown("# Title\n\n## Step\nText with **bold** and `code`.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n")
    assert "<h2>Step</h2>" in out and "<strong>bold</strong>" in out and "<code>code</code>" in out
    assert "<td>1</td>" in out and "<li>two</li>" in out and "Title" not in out
