=================
Account Tax UNECE
=================

.. 
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! This file is generated by oca-gen-addon-readme !!
   !! changes will be overwritten.                   !!
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! source digest: sha256:88d2e410241cd080a75d917d456d67d26dc250e6d998ffb60913448016b1f485
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

.. |badge1| image:: https://img.shields.io/badge/maturity-Production%2FStable-green.png
    :target: https://odoo-community.org/page/development-status
    :alt: Production/Stable
.. |badge2| image:: https://img.shields.io/badge/licence-LGPL--3-blue.png
    :target: http://www.gnu.org/licenses/lgpl-3.0-standalone.html
    :alt: License: LGPL-3
.. |badge3| image:: https://img.shields.io/badge/github-OCA%2Fcommunity--data--files-lightgray.png?logo=github
    :target: https://github.com/OCA/community-data-files/tree/18.0/account_tax_unece
    :alt: OCA/community-data-files
.. |badge4| image:: https://img.shields.io/badge/weblate-Translate%20me-F47D42.png
    :target: https://translation.odoo-community.org/projects/community-data-files-18-0/community-data-files-18-0-account_tax_unece
    :alt: Translate me on Weblate
.. |badge5| image:: https://img.shields.io/badge/runboat-Try%20me-875A7B.png
    :target: https://runboat.odoo-community.org/builds?repo=OCA/community-data-files&target_branch=18.0
    :alt: Try me on Runboat

|badge1| |badge2| |badge3| |badge4| |badge5|

This module adds two fields *UNECE Type Code* and *UNECE Category Code*
on taxes to allow the use of the standards written by the `United
Nations Economic Commission for Europe <http://www.unece.org>`__ (which
has 56 members states in Europe, America and Central Asia, cf
`Wikipedia <https://en.wikipedia.org/wiki/United_Nations_Economic_Commission_for_Europe>`__):

- the UNECE Tax Type code is defined in the `DataElement
  5153 <http://www.unece.org/trade/untdid/d97b/uncl/uncl5153.htm>`__,
- the UNECE Tax Category Code is defined in the `DataElement
  5305 <http://www.unece.org/trade/untdid/d97a/uncl/uncl5305.htm>`__.

This codification is part of the UNCL (United Nations Code List). This
codification is used for example in the two main international standards
for electronic invoicing:

- `Cross Industry
  Invoice <http://tfig.unece.org/contents/cross-industry-invoice-cii.htm>`__
  (CII),
- `Universal Business Language <http://ubl.xml.org/>`__ (UBL).

**Table of contents**

.. contents::
   :local:

Configuration
=============

1. Go to the menu *Accounting > Configuration > Accounting > Taxes*
2. Set the field *UNECE Type Code* (the value should be *VAT* for most
   of your taxes).
3. Set the field *UNECE Category Code*.

There are localization modules that fill this information for specific
chart of accounts, so this step shouldn't be needed if installed.

Bug Tracker
===========

Bugs are tracked on `GitHub Issues <https://github.com/OCA/community-data-files/issues>`_.
In case of trouble, please check there if your issue has already been reported.
If you spotted it first, help us to smash it by providing a detailed and welcomed
`feedback <https://github.com/OCA/community-data-files/issues/new?body=module:%20account_tax_unece%0Aversion:%2018.0%0A%0A**Steps%20to%20reproduce**%0A-%20...%0A%0A**Current%20behavior**%0A%0A**Expected%20behavior**>`_.

Do not contact contributors directly about support or help with technical issues.

Credits
=======

Authors
-------

* Akretion

Contributors
------------

- Alexis de Lattre <alexis.delattre@akretion.com>
- Andrea Stirpe <a.stirpe@onestein.nl>
- Levent Karakaş
- Pedro M. Baeza
- Nhan Tran <nhant@trobz.com>

Maintainers
-----------

This module is maintained by the OCA.

.. image:: https://odoo-community.org/logo.png
   :alt: Odoo Community Association
   :target: https://odoo-community.org

OCA, or the Odoo Community Association, is a nonprofit organization whose
mission is to support the collaborative development of Odoo features and
promote its widespread use.

.. |maintainer-alexis-via| image:: https://github.com/alexis-via.png?size=40px
    :target: https://github.com/alexis-via
    :alt: alexis-via

Current `maintainer <https://odoo-community.org/page/maintainer-role>`__:

|maintainer-alexis-via| 

This module is part of the `OCA/community-data-files <https://github.com/OCA/community-data-files/tree/18.0/account_tax_unece>`_ project on GitHub.

You are welcome to contribute. To learn how please visit https://odoo-community.org/page/Contribute.
