## Running it

This might take a lot amount of ram to parse the whole PDF ~19G

3m50 to run the msr.py on a 2x Xeon E5-2678v3 @2.50GHz
1m23 to run the msy.py on a 1x AMD EPYC 7543P @2.80GHz

```
pip install -r requirements.txt
python msr.py -d -p '/path/to/man-intel-vol-4.pdf
```

This requires at least Python 3.9. Not tested on other versions.

## Why ?

Because I ended up too many times reading the wrong table for the MSR I was searching for.

This can help but the man is still the source of truth.

Source used: Intel® 64 and IA-32 Architectures Software Developer’s Manual
Volume 4: Model-Specific Registers December 2022.

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
- [ ] Table 2-12: is 06_5FH a goldmont too? should be included
- [ ] Table 2-14: supported cpu:06_86H, 06_96H, or 06_9CH
- [ ] Table 2-47/2-48: missin supported cpu 06_97H, 06_9AH, and 06_BFH.
- [ ] Table 2-49: missin supported cpu pcore/ecore
- [ ] Table 2-52: missing 06_8FH
- [ ] Table 2-54: missing 06_85H
- [ ] Table 2-61: missing pentium supported cpu
- [ ] Verify that displayname / family is correct for all tables
- [ ] Table 2-53 is badly formatted on the pdf
- [ ] 18BH-18FH manualk patch for MSR_MCG_RESERVED1 to MSR_MCG_RESERVED5
- [ ] Table 2-23 p197 give package instead of msr_error_control in register name
- [ ] Table 2-6 p96 broken AF
