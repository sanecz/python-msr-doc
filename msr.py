# pylint: disable=line-too-long,too-few-public-methods,dangerous-default-value
import argparse
import logging
import math
import os
import re

from typing import Union, List, Dict, Any, Tuple, Pattern, Set

import multiprocessing as mp
from py_pdf_parser.loaders import load_file
from pathlib import Path

import camelot
import pdfminer
import yaml

import sys
# Avoid stack overflow on the man version 2022
sys.setrecursionlimit(5000)

# Sometimes it's written `Writable for this` or `Write only for`, we just ignore it atm
ACCESS_REGEXP = re.compile(r"\((([01BCKLMOPRSVWZ\-\/]+)(\s+in\s+SMM)?)\)")
BITFIELD_REGEXP = re.compile(r"\[\d+\:\d+\]")
# Table is somehow always consistent in the format `Table d-dd.`
TABLE_REGEXP = re.compile(r"^(Table \d-\d{1,2})\.\s+")
# At lease this is also close to be consistant
SEE_TABLE_REGEXP = re.compile(r"(?:(?:See\s+)?Table\s+(\d{1,2}-\d{1,2}))")
SEE_SECTION_REGEXP = re.compile(r"(?:(?:See\s+)?Section\s+([\d+\.?]+))")
SEE_APPENDIX_REGEXP = re.compile(r"(?:(?:See\s+)?Appendix\s+(\w[\.?\d+]+))")

SEE_MAPPING = {
    "see_table": SEE_TABLE_REGEXP,
    "see_section": SEE_SECTION_REGEXP,
    "see_appendix": SEE_APPENDIX_REGEXP
}

INDEX_START = "MSR Name and CPUID DisplayFamily_DisplayModel"

# P6 Family
# Intel Pentium III Xeon processor, Intel Pentium III processor
# Intel Pentium II Xeon processor, Intel Pentium II processor
# Intel Pentium Pro processor
P6_FAMILY = [
    "06_0BH", "06_08H", "06_07H",
    "06_06H", "06_05H", "06_03H",
    "06_01H", "06_0AH"
]

# NetBurst Family
# Intel Xeon Processor, Intel Pentium 4 processors
# Intel Xeon processor 7100, 5000 Series
# Intel Xeon processor MP, Pentium D processors
NETBURST_FAMILY = [
    "0F_06H", "0F_03H", "0F_04H",
    "0F_02H", "0F_0H",  "0F_01H"
]


logger = logging.getLogger(__name__)

class ParseMSRException(Exception):
    pass

def strip_spaces(string: str) -> str:
    return " ".join(string.split())

def str_to_list_int(string: str) -> List[int]:
    list_int = []
    for elem in string.split(","):
        elem = elem.strip()
        try:
            list_int.append(int(elem))
        except ValueError:
            continue
    return list_int


class MSRDescription:
    long_description: str
    description: str
    comments: str
    access: str
    see_table: str
    see_section: str
    see_appendix: str
    scope: str
    shared: str
    model_availability: List[int]


    def parse(self, header: List[str], datas: List[str]) -> None:
        description_index = self.parse_format_by_header(header, datas)
        data = datas[description_index]

        access_type = ACCESS_REGEXP.search(data)
        if access_type:
            # So many ways to define access
            # See table 2-1 in section 2-2 in vol 2 there is 27 ways to define it
            self.access = strip_spaces(access_type.groups()[0])
            data = data.replace(access_type.group(), "")  # remove from description

        splitted_data = data.split("\n")
        # There is no rule in this pdf for guessing the short description, let's guess based on some tokens
        if ":" in splitted_data[0] and not BITFIELD_REGEXP.search(splitted_data[0]):
            # don't split on ":" if it's a bitfield (i.e [32:2])
            description = splitted_data[0].split(":")[0]
        elif "(" in splitted_data[0]:
            # Split before the parenthesis so we might have something readable
            description = splitted_data[0].split("(")[0]
        elif "," in splitted_data[0]:
            # Probably "See section xxxx or See table xxxx"
            description = splitted_data[0].split(",")[0]
        elif "." in splitted_data[0] :
            # who knows, maybe the sentence is ended on this list
            description = splitted_data[0].split(".")[0]
        else:
            # full sentence ?
            description = splitted_data[0]

        self.description = strip_spaces(description)
        if len(splitted_data) != 1:
            # if we have multi line then it's '''long''' description
            self.long_description = strip_spaces(data)

        for section, regexp in SEE_MAPPING.items():
            # Check for `see table` `see appendix` and `see section`
            # TODO: maybe add see http? for some msr they have an url to biosbit
            self.parse_see_other(section, regexp, data)

    def parse_see_other(self, other: str, other_regexp: Pattern[str], data: str) -> None:
        found_see_other = other_regexp.findall(data)
        if found_see_other:
            setattr(self, other, found_see_other)

    def parse_format_by_header(self, header: List[str], data: List[str]) -> int:
        logger.debug("Header: %s" % header)
        logger.debug("Data: %s"  % data)
        # Sometime when we parse the header, even if it's displayed 'hex' 'dec' in the pdf
        # we are not seeing it in the header list, so i consider those as 'broken' tables
        # or sometimes they just forgot the headers
        if header[2].lower() == "bit description" and len(header) == 3:
            # broken table 2-5{2,4}
            # format: [hex, name/bits, msr/bit desc]
            self.bit = data[1]
            description_idx = 2
        elif header[3].lower() == "bit description" and len(header) == 4:
            # table 2-52 to 2-54
            # format: [hex, dec, name/bits, msr/bit desc]
            description_idx = 3
        elif header[2].lower() == "scope":
            # broken table 2-5 to 2-47
            # format: [hex, name/bits, scope, bit descr]
            self.bit = data[1]
            self.scope = data[2]
            description_idx = 3
        elif header[3].lower() == "scope":
            # table 2-5 to 2-47
            # format: [hex, dec, name/bits, scope , bit descr]
            self.scope = data[3]
            description_idx = 4
        elif header[3].lower() == "shared/ unique":
            # table 2-3,4 and 2-47 && table 2-51
            # format: [hex, dec, name/bits, shared/uniq, bit descr]
            self.shared = data[3]
            description_idx = 4
        elif header[2].lower() == "model avail- ability":  # it's cut in the middle ffs
            # broken table 2-48 to 2-50
            # format: [hex, name/bits, model avail, shared/uniq, bit descr]
            self.bit = data[1]
            data[2] = " ".join(data[2].split("\n"))  # sometimes it's multiline
            self.model_availability = str_to_list_int(data[2])
            self.shared = data[3]
            description_idx = 4
        elif header[3].lower() == "model avail- ability":  # it's cut in the middle ffs
            # table 2-48 to 2-50
            # format: [hex, dec, name/bits, model avail, shared/uniq, bit descr]
            data[3] = " ".join(data[3].split("\n"))  # sometimes it's multiline
            self.model_availability = str_to_list_int(data[3])
            self.shared = data[4]
            description_idx = 5
        elif header[4].lower() == "comment":
            # table 2-2
            # format: [hex, dec, name/bits, msr/bit desc, comment]
            description_idx = 3
            self.comments = strip_spaces(data[4])
        else:
            raise ParseMSRException(f"Unknown format {header}")

        return description_idx

    def patch(self, patch_dict: Dict[str, Any]) -> None:
        for key, value in patch_dict.items():
            if key in ("bitfield", "msr"):
                # We do not want to modify this
                continue
            setattr(self, key, value)


class MSRBit(MSRDescription):
    bit: str

    def __init__(self, data: List[str], header: List[str]):
        self.bit = data[2]  # may be overriden by guess_format_by_header if the table is broken
        self.parse(header, data)

    def __repr__(self) -> str:
        return f"<MSRBit({self.bit}: {self.description})>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return other == self.bit

    def to_dict(self) -> Dict[str,str]:
        description = {
            "bit": self.bit,
            "access": getattr(self, "access", None),
            "long_description": getattr(self, "long_description", None),
            "description": self.description,
            "comments": getattr(self, "comments", None),
            "shared": getattr(self, "shared", None),
            "access": getattr(self, "access", None),
            "see_table": getattr(self, "see_table", None),
            "see_section": getattr(self, "see_section", None),
            "see_appendix": getattr(self, "see_appendix", None),
            "model_availability": getattr(self, "model_availability", None)
        }

        return {k:v for k, v in description.items() if v}


class MSR(MSRDescription):
    name: str
    value: str
    alt_name: str
    fields: List[MSRBit]

    def __init__(self, data: List[str], header: List[str]):
        self.parse(header, data)
        self.value = strip_spaces(data[0]).replace(" ", "")
        # TODO: test if value is hex or hex and contains "_"
        # TODO: otherwise raise Exception (i.e end of table 2-23)

        # Depends on the header we are changing your way of parsing the table
        # except for the register always position 0
        self._set_name(getattr(self, "bit", data[2]))  # dirty hack to see if we are in a broken table
        self.fields = []

    def _set_name(self, data: str) -> None:
        """
        Try to retrieive former MSR name if possible
        """
        # alt name is guessed only if there is a parenthesis
        if "(" in data:
            # This might be a register/bitfield on multiline i.e
            # IA32_MTRR_PHYSBASE0
            # (MTRRphysBase0)
            # or everything in a single line i.e `IA32_MCG_CAP (MCG_CAP)`
            data = "".join(data.split("\n"))
            name, alt_name = data.split("(")
            self.name = name.strip()
            self.alt_name = alt_name.replace(")", "").strip()
        else:
            # sometimes the register_name bitfield is multiline i.e
            # IA32_MONITOR_FILTER_
            # SIZE
            # so either it's only on 2 lines to display the name or it's broken
            # so this mean we need to fix it by hand, just display the 2 first lines
            data = ''.join(data.split("\n")[0:2])
            self.name = data.strip()

    def __repr__(self) -> str:
        return f"<MSRDescription({self.value}): {self.name or self.bit} {len(self.fields) or 1} bitfield(s)>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return other == self.value

    def patch_msr(self, msr):
        self.patch(msr)
        for bitfield in msr.get("bitfields", []):
            try:
                index = self.fields.index(bitfield["bit"])
                if msr.get("_type") == "delete":
                    self.fields.pop(index)
                else:
                    self.fields[index].patch(bitfield)
            except ValueError:
                # bitfield from patch not in self.fields, creating a new MSRBit
                # and avoid __init__
                # FIX: split init?
                new_bitfield = MSRBit.__new__(MSRBit)
                new_bitfield.patch(bitfield)
                self.fields.append(new_bitfield)


    def to_dict(self) -> Dict[str, Union[str, MSRBit]]:
        description =  {
            "value": self.value,
            "name": self.name,
            "alt_name": getattr(self, "alt_name", None),
            "bitfields": [field.to_dict() for field in self.fields],
            "scope": getattr(self, "scope", None),
            "shared": getattr(self, "shared", None),
            "access": getattr(self, "access", None),
            "description": getattr(self, "description", None),
            "long_description": getattr(self, "long_description", None),
            "see_table": getattr(self, "see_table", None),
            "see_section": getattr(self, "see_section", None),
            "see_appendix": getattr(self, "see_appendix", None),
            "comments": getattr(self, "comments", None),
            "model_availability": getattr(self, "model_availability", None)
        }

        # clean up everything
        return {k:v for k, v in description.items() if v}


class Table:
    name: str
    full_name: str
    msr: List[MSR] = []
    supported_cpus: List[str]

    def __init__(self, name: str, full_name: str):
        self.name = name
        self.full_name = strip_spaces(full_name)
        self.msr = []

        # Table 2-2 is IA32 MSR, all cpus should support it
        self.supported_cpus = []

    def patch_table(self, table) -> None:
        if table.get("supported_cpu"):
            self.supported_cpus = table["supported_cpu"]

        if table.get("full_name"):
            self.full_name = table["full_name"]

        for msr in table.get("msr", []):
            try:
                index = self.msr.index(msr["value"])
            except ValueError as e:
                # Creating a new msr and push it to the end
                # and create the bitfields
                index = -1
                new_msr = MSR.__new__(MSR)
                new_msr.fields = []
                new_msr.patch(msr)
                self.msr.append(new_msr)

                if msr.get("_type") == "delete":
                    self.msr.pop(index)
                else:
                    self.msr[index].patch_msr(msr)


    def to_dict(self) -> Dict[str, Union[str, List[Dict[str, Union[str, MSRBit]]], List[str]]]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "supported_cpu": list(sorted(set(self.supported_cpus))),  # clean garbage then back to list
            "msr": [msr.to_dict() for msr in self.msr]
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return NotImplemented
        return other == self.name

    def __repr__(self) -> str:
        return f"<Table({self.name}: {len(self.msr)} MSRs)>"


def str_presenter(dumper: yaml.dumper.Dumper, data: str) -> yaml.nodes.ScalarNode:
    # TODO: i think it does not work
    if len(data.splitlines()) > 1:  # check for multiline string
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


# Stolen from https://github.com/atlanhq/camelot/issues/395

def top_mid(bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, bbox[3])


def bottom_mid(bbox: Tuple[float, float, float]) -> Tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, bbox[1])


def get_distance(point1: Tuple[float, float], point2: Tuple[float, float]) -> float:
    return math.sqrt((point1[0] - point2[0]) ** 2 + (point1[1] - point2[1]) ** 2)


def get_closest_text(table: camelot.core.Table, htext_objs: List[pdfminer.layout.LTTextLineHorizontal]) -> List[str]:
    min_distance = 100.0
    idx = 0
    best_guess = []
    table_mid = top_mid(table._bbox)  # Middle of the TOP of the table

    for obj in htext_objs:
        text_mid = bottom_mid(obj.bbox)  # Middle of the BOTTOM of the text
        distance = get_distance(text_mid, table_mid)
        if distance < min_distance:
            best_guess.append(obj.get_text().strip())
            min_distance = distance

    # Find all text that are between `Table` (included)
    # And the fromat is "Table xxx." (dot is important)
    for idx, _ in enumerate(best_guess):
        if best_guess[idx].startswith("Table") and best_guess[idx].split(" ")[1][-1] == '.':
            break

    # and `Register` / `Fields` / `Bit Description` (excluded)
    # or `Contd.` (included)
    for end_idx in range(idx, len(best_guess)):
        if best_guess[end_idx].split(' ')[0] in ("Register", "Fields", "Bit"):
            end_idx -= 1
            break
        if "Contd" in best_guess[end_idx]:
            break

    return best_guess[idx:end_idx + 1]

# Thank you! :)


class PDFHandler(camelot.handlers.PDFHandler):
    def _parse_page(
            self,
            page_id: int,
            tempdir: str,
            parser: camelot.parsers.lattice.Lattice,
            suppress_stdout: bool = False,
            layout_kwargs: Dict[str, Any] = {}
    ) -> Tuple[List[camelot.core.Table], List[str]]:
        tables: List[camelot.core.Table] = []
        titles: List[str] = []

        self._save_page(self.filepath, page_id, tempdir)
        page = os.path.join(tempdir, "page-{0}.pdf".format(page_id))

        tables = parser.extract_tables(
            page, suppress_stdout=suppress_stdout, layout_kwargs=layout_kwargs
        )

        layout, _ = camelot.utils.get_page_layout(page)
        htext_objs = camelot.utils.get_text_objects(layout, ltype="horizontal_text")

        for table in tables:
            titles.append(' '.join(get_closest_text(table, htext_objs)))

        return tables, titles


    def parse(
        self,
        flavor: str = "lattice",
        suppress_stdout: bool = False,
        layout_kwargs: Dict[str,str] = {},
        **kwargs: Dict[str, Any]
    ) -> camelot.core.TableList:
        # Retrieve pages AND titles
        # Add multiprocessing because 400 pages is very slow to parse
        tables: List[Tuple[camelot.core.Table, str]] = []

        cpu_count = mp.cpu_count()
        logger.info("Start pdf parsing")
        with camelot.utils.TemporaryDirectory() as tempdir:
            parser = camelot.parsers.Lattice(**kwargs) if flavor == "lattice" else camelot.parsers.Stream(**kwargs)
            self._parse_page(self.pages[0], tempdir, parser, suppress_stdout, layout_kwargs)
            with mp.get_context("spawn").Pool(processes=cpu_count) as pool:
                jobs = [
                    pool.apply_async(
                        self._parse_page,
                        (page_id, tempdir, parser, suppress_stdout, layout_kwargs)
                    ) for page_id in self.pages
                ]

                for job in jobs:
                    table_list, title_list = job.get()
                    tables.extend(zip(table_list, title_list))
        logger.info("End of pdf parsing")
        return camelot.core.TableList(sorted(tables))


def parse_pdf(path: str) -> Tuple[Set[str], List[Table]]:
    table_list: List[Table] = []
    cpu_list: List[str] = ["05_09H"]

    logger.info("Reading pdf")

    # MSR are described from page 19 to 394, using man intel vol 4 Order October 2019
    # MSR are described from page 19 to 504, using man intel vol 4 Order 2022
    # page 17 to 19 describe available CPU families/models
    # ofc consistency is way too hard, so I added manually 05_09H
    pdf = PDFHandler(path, pages="17-end")
    tables = pdf.parse()

    for table, title in tables:
        table_id = TABLE_REGEXP.search(title).groups()[0]
        if table_id == "Table 2-1":  # not a msr table
            for data in table.data:
                if data[0].startswith("DisplayFamily"):
                    continue
                cpu_list.extend([strip_spaces(cpu) for cpu in data[0].split(",")])
            continue

        current_table = get_table_by_name(table_list, table_id)

        if not current_table:
            current_table = Table(table_id, title)
            table_list.append(current_table)

        logger.info("Working on page %s table %s", table.page, table_id)

        header = [strip_spaces(header) for header in table.data[0]]
        for data in table.data[2:]:
            try:
                if data[0]:  # There is a register address so it's a new MSR
                    current_table.msr.append(MSR(data, header))
                else:        # Description of the bit fields, appends it to the last register
                    current_table.msr[-1].fields.append(MSRBit(data, header))
            except Exception as excp:  # pylint: disable=W0703
                # Ignore error on page 136 because it's badly formatted and not usable
                # Ignore error when you start in the middle of a bitfield description
                # (usually it breaks at current_table.msr[-1] giving IndexError
                logger.exception(excp)

    # just make uniq the cpu list
    return set(cpu_list), table_list


def get_table_by_name(table_list: List[Table], table_name: str) -> Union[Table, None]:
    for table in table_list:
        if table_name == table:
            return table
    return None


def parse_cpus(path: str, cpu_list: Set[str], table_list: List[Table]) -> None:
    pdf = load_file(path)

    table = get_table_by_name(table_list, "Table 2-2")
    table.supported_cpus = cpu_list

    # MSR index is from page 426 to page 506 in man version 2022
    for page in pdf.pages[426:506]:
        for idx, elem in enumerate(page.elements):
            # Move until we find the start
            if elem.text().startswith("Location"):
                break
        elem_iterator = iter(page.elements[idx+1:])
        for elem in elem_iterator:
            text = elem.text()
            # multiple formats
            # df_dm1, df_dm2 ..... See Table xx
            # sometimes it's
            # df_dm1, df_dm2 See Table xx
            # df_dm3 .........
            # sometimes it's
            # df_dm .......... See Table xx and
            #                  Table yy

            if text.startswith("See Table"):
                # This might be alone in the line so next line is a multi line with all the cpu families
                logger.debug("Multi line table detected %s" % text)
                table_name = text
                cpu_list = next(elem_iterator).text().replace("\n", "").split(".")[0]
                logger.debug("CPUs found %s" % cpu_list)
            elif "." in text and "Vol" not in text:
                # "Vol. 4 " is the end of the page
                logger.debug("Dot found in text %s" % text)
                if not "See Table" in text:
                    # another broken thing, possibly on next line
                    cpu_list = text.split(".")[0]
                    table_name = next(elem_iterator).text()
                else:
                    cpu_list, table_name = list(filter(lambda x: x.strip(), text.split(".")))
            elif "H," in text:
                # like we have "XX_XXH, YY_YYH" instead of the msr name
                #        match here  ^^
                # broken case
                cpu_list = text.replace("\n", "").split(".")[0]
                table_name = next(elem_iterator).text().replace("\n", "")
            else:
                logger.debug("Nothing found in text %s" % text)
                # nothing to see here, probably msr name
                continue

            logger.debug("Extracted name %s and list %s" % (table_name, cpu_list))

            table_name_list = [table_name]
    
            if "and" in table_name:
                table_name_list.append(next(elem_iterator).text())

            cpu_list = [cpu.strip() for cpu in cpu_list.strip().split(",") if cpu.strip()]

            if "0FH" in cpu_list:
                # replace by the whole family
                cpu_list.pop(cpu_list.index("0FH"))
                cpu_list.extend(NETBURST_FAMILY)

            if "P6 Family" in cpu_list:
                # if there is p6 family in list, replace with all the
                # cpufamily_cpumodel in this p6 family
                cpu_list.pop(cpu_list.index("P6 Family"))
                cpu_list.extend(P6_FAMILY)


            for table_name in table_name_list:
                table = get_table_by_name(table_list, table_name.replace("See", "").strip())
    
                if table:
                    table.supported_cpus.extend(cpu_list)


def dump_tables(table_list: List[Table]) -> None:
    logger.info("Dumping tables")
    yaml.add_representer(str, str_presenter)

    for table in table_list:
        with open(f"output/{table.name.lower().replace(' ', '-')}.yaml", "w") as handle:
            handle.write(
                yaml.dump(
                    table.to_dict(), sort_keys=False, explicit_start=True,
                    allow_unicode=True, default_flow_style=False, width=float("inf")
                )
            )

    
def apply_patches(table_list: List[Table]) -> None:
    patchdir = Path(__file__).parent.resolve() / Path("patches")
    for patch in patchdir.iterdir():

        with open(patch, "r") as handle:
            patch_dict = yaml.load(handle, Loader=yaml.SafeLoader)

        table = get_table_by_name(table_list, patch_dict["name"])

        if table:
            table.patch_table(patch_dict)


if __name__ == "__main__":
    argparser = argparse.ArgumentParser()

    argparser.add_argument('-v', '--verbose', action='store_true')
    argparser.add_argument('-d', '--debug', action='store_true')
    argparser.add_argument('-p', '--path', required=True)

    args = argparser.parse_args()
    LEVEL = logging.ERROR

    if args.debug:
        LEVEL = logging.DEBUG
    elif args.verbose:
        LEVEL = logging.INFO

    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    logger.setLevel(LEVEL)

    logging.addLevelName(logging.INFO, "\033[1;32m%s\033[1;0m" % logging.getLevelName(logging.INFO))
    logging.addLevelName(logging.ERROR, "\033[1;41m%s\033[1;0m" % logging.getLevelName(logging.ERROR))
    logging.addLevelName(logging.DEBUG, "\033[1;34m%s\033[1;0m" % logging.getLevelName(logging.DEBUG))

    cpus, tables = parse_pdf(args.path)
    parse_cpus(args.path, cpus, tables)
    apply_patches(tables)
    dump_tables(tables)
