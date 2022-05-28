## Running it

This might take a lot amount of ram to parse the whole PDF (~10G)

```
pip install -r requirements.txt
python msr.py -d -p '/path/to/man-intel-vol-4.pdf
```

This requires at least Python 3.9. Not tested on other versions.

## Why ?

Because I ended up too many times reading the wrong table for the MSR I was searching for.

This can help but the man is still the source of truth.

Source used: Intel® 64 and IA-32 Architectures Software Developer’s Manual
Volume 4: Model-Specific Registers October 2019.

This has not been tested with other versions and might break and/or display wrong results.


## Format

If not marked as 'optional', the field will always exist

```yaml
name: Table X-YZ
full_name: Table X-YZ. MSR for this family
supported_cpu:
- DF_DM  # DisplayFamily_DisplayModel
- DF_DM
- ...
msr:
- name: MSR_NAME
  alt_name: ALT_MSR_NAME
  value: 0H
  access: R/O etc [optional]
  scope: Thread/Package/Module/Core [optional]
  shared: Shared/Unique [optional]
  model_availability: List of models [optional]
  description: Some description [optional]
  long_description: |
    This description might be multiline [optional]
  see_section: [optional]
  - 'Y.A.B.C.D'
  see_table: [optional]
  - 'Y-Z'
  see_appendix: [optional]
  - 'A.X'
  comments: Some comments (usually on Table 2-2) [optional]

  bitfields: [optional]
  - bit: [X|X:Y]      # bit or range
    description: Some description
    long_description: This description might be multiline [optional]
    access: R/O etc [optional]
    scope: Thread/Package/Module/Core [optional]
    shared: Shared/Unique [optional]
    model_availability: List of models [optional]
    see_section: [optional]
    - 'Y.A.B.C.D'
    see_table: [optional]
    - 'Y-Z'
    see_appendix: [optional]
    - 'A.X'
```

TODO:
- [ ] README :)
- [ ] Verify that displayname / family is correct for all tables
- [ ] Properly reformat `access`
- [ ] P6 Family -> correct format / in supported cpus p6 family is splitted on space...
- [ ] Patches
- [ ] Table 2-53 is badly formatted on the pdf
- [ ] 18BH-18FH manualk patch for MSR_MCG_RESERVED1 to MSR_MCG_RESERVED5
- [ ] Table 2-23 p197 give package instead of msr_error_control in register name
- [ ] Table 2-6 p96 broken AF
- [ ] MSR_PPERF shown in supported cpu