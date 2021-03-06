from pathlib import Path
import re

from docutils import nodes
from docutils import transforms
from docutils.transforms import peps
from sphinx import errors

from pep_sphinx_extensions.config import pep_url
from pep_sphinx_extensions.pep_processor.transforms import pep_zero


class PEPParsingError(errors.SphinxError):
    pass


# PEPHeaders is identical to docutils.transforms.peps.Headers excepting bdfl-delegate, sponsor & superseeded-by
class PEPHeaders(transforms.Transform):
    """Process fields in a PEP's initial RFC-2822 header."""

    # Run before pep_processor.transforms.pep_title.PEPTitle
    default_priority = 330

    def apply(self) -> None:
        if not Path(self.document["source"]).match("pep-*"):
            return  # not a PEP file, exit early

        if not len(self.document):
            raise PEPParsingError("Document tree is empty.")

        header = self.document[0]
        if not isinstance(header, nodes.field_list) or "rfc2822" not in header["classes"]:
            raise PEPParsingError("Document does not begin with an RFC-2822 header; it is not a PEP.")

        # PEP number should be the first field
        pep_field = header[0]
        if pep_field[0].astext().lower() != "pep":
            raise PEPParsingError("Document does not contain an RFC-2822 'PEP' header!")

        # Extract PEP number
        value = pep_field[1].astext()
        try:
            pep = int(value)
        except ValueError:
            raise PEPParsingError(f"'PEP' header must contain an integer. '{value}' is invalid!")

        # Special processing for PEP 0.
        if pep == 0:
            pending = nodes.pending(pep_zero.PEPZero)
            self.document.insert(1, pending)
            self.document.note_pending(pending)

        # If there are less than two headers in the preamble, or if Title is absent
        if len(header) < 2 or header[1][0].astext().lower() != "title":
            raise PEPParsingError("No title!")

        fields_to_remove = []
        for field in header:
            name = field[0].astext().lower()
            body = field[1]
            if len(body) == 0:
                # body is empty
                continue
            elif len(body) > 1:
                msg = f"PEP header field body contains multiple elements:\n{field.pformat(level=1)}"
                raise PEPParsingError(msg)
            elif not isinstance(body[0], nodes.paragraph):  # len(body) == 1
                msg = f"PEP header field body may only contain a single paragraph:\n{field.pformat(level=1)}"
                raise PEPParsingError(msg)

            para = body[0]
            if name in {"author", "bdfl-delegate", "pep-delegate", "sponsor"}:
                # mask emails
                for node in para:
                    if isinstance(node, nodes.reference):
                        pep_num = pep if name == "discussions-to" else -1
                        node.replace_self(peps.mask_email(node, pep_num))
            elif name in {"replaces", "superseded-by", "requires"}:
                # replace PEP numbers with normalised list of links to PEPs
                new_body = []
                space = nodes.Text(" ")
                for ref_pep in re.split(r",?\s+", body.astext()):
                    new_body.append(nodes.reference(
                        ref_pep, ref_pep,
                        refuri=(self.document.settings.pep_base_url + pep_url.format(int(ref_pep)))))
                    new_body.append(space)
                para[:] = new_body[:-1]  # drop trailing space
            elif name in {"last-modified", "content-type", "version"}:
                # Mark unneeded fields
                fields_to_remove.append(field)

        # Remove unneeded fields
        for field in fields_to_remove:
            field.parent.remove(field)


def _mask_email(ref: nodes.reference, pep_num: int = -1) -> nodes.reference:
    """Mask the email address in `ref` and return a replacement node.

    `ref` is returned unchanged if it contains no email address.

    If given an email not explicitly whitelisted, process it such that
    `user@host` -> `user at host`.

    If given a PEP number `pep_num`, add a default email subject.

    """
    if "refuri" in ref and ref["refuri"].startswith("mailto:"):
        non_masked_addresses = {"peps@python.org", "python-list@python.org", "python-dev@python.org"}
        if ref['refuri'].removeprefix("mailto:").strip() in non_masked_addresses:
            replacement = ref[0]
        else:
            replacement_text = ref.astext().replace("@", "&#32;&#97;t&#32;")
            replacement = nodes.raw('', replacement_text, format="html")

        if pep_num != -1:
            replacement['refuri'] += f"?subject=PEP%20{pep_num}"
        return replacement
    return ref
