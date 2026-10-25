"""Dark desktop component palettes, independent of application theme variants."""
from __future__ import annotations
from dataclasses import dataclass

# Each profile includes its full dark surface/state palette and 16 ANSI colors.
# Row: id, display name, background, foreground, accent, named color roles.
# An accent may fill selections and controls. Main surfaces always stay dark.
CATALOG = (
 ('midnight-slate', 'Midnight Slate', '111827', 'e5edf8', '7cb8ff', {
  'surface': '181f2e', 'surface_alt': '212837', 'hover': '22324a', 'pressed': '2c405d',
  'muted': '9fa7b3', 'disabled': '6a717f', 'selection_text': '111111',
  'accent_hover': '8fc2fe', 'accent_pressed': '6b9edc', 'border': '4f75a4',
  'glow': '86bdfe', 'shadow': '0a0e17', 'success': '8cd2b0', 'warning': 'e4c686', 'error': 'e194aa',
  'ansi': ('353c4b', 'e194aa', '8cd2b0', 'e4c686', '7cb8ff', 'b9a4e3', '75d1df', 'e5edf8', '9fa7b3', 'e2a2b6', '9ad6bc', 'e4cc98', '8dc0fe', 'c0b0e6', '87d5e3', 'e5edf8')}),
 ('nordic-frost', 'Nordic Frost', '242c3b', 'e7edf4', '88c0d0', {
  'surface': '2b3341', 'surface_alt': '333a49', 'hover': '344453', 'pressed': '3d5160',
  'muted': 'a7adb7', 'disabled': '767d89', 'selection_text': '111111',
  'accent_hover': '99c8d6', 'accent_pressed': '78a8b8', 'border': '5e8291',
  'glow': '92c4d4', 'shadow': '161a23', 'success': '8dd3aa', 'warning': 'e6c782', 'error': 'e295a4',
  'ansi': ('454d5a', 'e295a4', '8dd3aa', 'e6c782', '88c0d0', 'bba6db', '78d2d7', 'e7edf4', 'a7adb7', 'e3a3b1', '9bd7b6', 'e6cd94', '97c7d6', 'c2b1df', '8ad6dc', 'e7edf4')}),
 ('mocha-rose', 'Mocha Rose', '241e2e', 'f2e4f4', 'e6a1c7', {
  'surface': '2b2535', 'surface_alt': '332d3d', 'hover': '433346', 'pressed': '543f54',
  'muted': 'aea3b3', 'disabled': '7b7181', 'selection_text': '111111',
  'accent_hover': 'e8adcf', 'accent_pressed': 'c78caf', 'border': '956a87',
  'glow': 'e7a8cc', 'shadow': '16121c', 'success': '99cfa9', 'warning': 'efc481', 'error': 'ef91a2',
  'ansi': ('474050', 'ef91a2', '99cfa9', 'efc481', 'e6a1c7', 'cca0d9', '89ccd5', 'f2e4f4', 'aea3b3', 'ef9eaf', 'a7d2b5', 'efc993', 'e8acce', 'd2abdd', '9ad0da', 'f2e4f4')}),
 ('forest-mist', 'Forest Mist', '15251f', 'e1eee5', '88c9a2', {
  'surface': '1c2c26', 'surface_alt': '24342e', 'hover': '273f34', 'pressed': '324e40',
  'muted': '9eaca4', 'disabled': '6b7972', 'selection_text': '111111',
  'accent_hover': '98d0ae', 'accent_pressed': '76af8d', 'border': '58846b',
  'glow': '91cda9', 'shadow': '0d1613', 'success': '8dd4a4', 'warning': 'e6c87d', 'error': 'e2979e',
  'ansi': ('384741', 'e2979e', '8dd4a4', 'e6c87d', '88c9a2', 'bba7d2', '78d4ce', 'e1eee5', '9eaca4', 'e2a5a9', '9ad8ae', 'e5ce8e', '96cfad', 'c1b2d5', '89d8d2', 'e1eee5')}),
 ('ocean-glass', 'Ocean Glass', '122632', 'e0f0f5', '6dcfda', {
  'surface': '192d39', 'surface_alt': '213541', 'hover': '21414d', 'pressed': '29505c',
  'muted': '9cadb5', 'disabled': '697b84', 'selection_text': '111111',
  'accent_hover': '82d5df', 'accent_pressed': '5eb4bf', 'border': '478893',
  'glow': '79d2dd', 'shadow': '0b171e', 'success': '8ad5ab', 'warning': 'e3c983', 'error': 'df97a5',
  'ansi': ('354853', 'df97a5', '8ad5ab', 'e3c983', '6dcfda', 'b6a8dc', '73d5d8', 'e0f0f5', '9cadb5', 'dfa5b2', '98d9b7', 'e3cf95', '7fd4de', 'bdb4e0', '84d9dd', 'e0f0f5')}),
 ('amber-dusk', 'Amber Dusk', '292217', 'f3ead7', 'e6bd6b', {
  'surface': '30291e', 'surface_alt': '383125', 'hover': '473b24', 'pressed': '58492c',
  'muted': 'b0a898', 'disabled': '7e7668', 'selection_text': '111111',
  'accent_hover': 'e8c57e', 'accent_pressed': 'c8a45e', 'border': '977c48',
  'glow': 'e7c276', 'shadow': '19140e', 'success': '99d39d', 'warning': 'efc778', 'error': 'ef9596',
  'ansi': ('4b4438', 'ef9596', '99d39d', 'efc778', 'e6bd6b', 'cca5c8', '89d2c4', 'f3ead7', 'b0a898', 'f0a3a0', 'a7d7a6', 'f0cd87', 'e8c47c', 'd2b0ca', '9ad6c7', 'f3ead7')}),
 ('lavender-ink', 'Lavender Ink', '221f35', 'ebe7fa', 'b6a5ed', {
  'surface': '29263c', 'surface_alt': '312e44', 'hover': '3a3452', 'pressed': '474063',
  'muted': 'a9a5b9', 'disabled': '767388', 'selection_text': '111111',
  'accent_hover': 'c0b1ef', 'accent_pressed': '9e90d0', 'border': '786da0',
  'glow': 'bbacee', 'shadow': '141320', 'success': '93d0ad', 'warning': 'eac485', 'error': 'e892a7',
  'ansi': ('444156', 'e892a7', '93d0ad', 'eac485', 'b6a5ed', 'c3a1e0', '80cddc', 'ebe7fa', 'a9a5b9', 'e8a0b4', 'a1d4b9', 'eaca98', 'beb0ef', 'c9ace4', '91d1e1', 'ebe7fa')}),
 ('solar-clay', 'Solar Clay', '30211d', 'f7e5dc', 'e9a083', {
  'surface': '372824', 'surface_alt': '3f302b', 'hover': '4e352d', 'pressed': '5e4136',
  'muted': 'b5a49d', 'disabled': '84736d', 'selection_text': '111111',
  'accent_hover': 'ecac93', 'accent_pressed': 'cb8c73', 'border': '9b6b58',
  'glow': 'eaa78c', 'shadow': '1d1411', 'success': '9acfa0', 'warning': 'efc47a', 'error': 'ef919a',
  'ansi': ('52423d', 'ef919a', '9acfa0', 'efc47a', 'e9a083', 'cca0cd', '89ccc9', 'f7e5dc', 'b5a49d', 'f09ea5', 'a9d3aa', 'f0c98a', 'ebab91', 'd3abcf', '9bd0cc', 'f7e5dc')}),
 ('glacier-blue', 'Glacier Blue', '17293b', 'e6f0fb', '93c4f5', {
  'surface': '1e3042', 'surface_alt': '273849', 'hover': '2b4259', 'pressed': '36506a',
  'muted': 'a2aebc', 'disabled': '6e7d8c', 'selection_text': '111111',
  'accent_hover': 'a2ccf6', 'accent_pressed': '7fabd7', 'border': '5f83a7',
  'glow': '9bc8f6', 'shadow': '0e1923', 'success': '8fd4af', 'warning': 'e7c885', 'error': 'e496a8',
  'ansi': ('3a4b5c', 'e496a8', '8fd4af', 'e7c885', '93c4f5', 'bda6e1', '7ad3dd', 'e6f0fb', 'a2aebc', 'e4a4b5', '9dd8bb', 'e7ce98', 'a0cbf6', 'c4b2e5', '8bd8e2', 'e6f0fb')}),
 ('sage-linen', 'Sage Linen', '242b23', 'e7ecdf', 'aec99a', {
  'surface': '2b322a', 'surface_alt': '333931', 'hover': '3a4436', 'pressed': '465241',
  'muted': 'a7aca1', 'disabled': '767c72', 'selection_text': '111111',
  'accent_hover': 'b8cfa6', 'accent_pressed': '98b087', 'border': '748768',
  'glow': 'b4cca1', 'shadow': '161a15', 'success': '92d4a3', 'warning': 'e9c87c', 'error': 'e7979d',
  'ansi': ('454c43', 'e7979d', '92d4a3', 'e9c87c', 'aec99a', 'c2a7d1', '7ed4cd', 'e7ecdf', 'a7aca1', 'e7a5a8', 'a0d8ad', 'e9ce8c', 'b7cfa5', 'c8b2d3', '8fd8d0', 'e7ecdf')}),
 ('plum-velvet', 'Plum Velvet', '2c1d30', 'f3e3f4', 'dba1e2', {
  'surface': '332437', 'surface_alt': '3b2c3f', 'hover': '48324c', 'pressed': '583e5c',
  'muted': 'b1a2b3', 'disabled': '807082', 'selection_text': '111111',
  'accent_hover': 'dfade5', 'accent_pressed': 'bf8cc6', 'border': '926a97',
  'glow': 'dda8e4', 'shadow': '1a111d', 'success': '98cfac', 'warning': 'eec484', 'error': 'ed91a6',
  'ansi': ('4e3f51', 'ed91a6', '98cfac', 'eec484', 'dba1e2', 'caa0de', '87ccda', 'f3e3f4', 'b1a2b3', 'ee9eb2', 'a7d2b8', 'efc996', 'dface5', 'd1abe2', '98d0de', 'f3e3f4')}),
 ('copper-stone', 'Copper Stone', '292522', 'f0e8e0', 'dca785', {
  'surface': '302c29', 'surface_alt': '383430', 'hover': '463a32', 'pressed': '56463b',
  'muted': 'aea8a1', 'disabled': '7d7772', 'selection_text': '111111',
  'accent_hover': 'e0b395', 'accent_pressed': 'bf9275', 'border': '91705b',
  'glow': 'deae8e', 'shadow': '191614', 'success': '98d0a0', 'warning': 'eec57a', 'error': 'ed929a',
  'ansi': ('4b4642', 'ed929a', '98d0a0', 'eec57a', 'dca785', 'caa1cd', '87cec9', 'f0e8e0', 'aea8a1', 'eda0a5', 'a6d4aa', 'eecb8a', 'dfb194', 'd0acd0', '98d2cd', 'f0e8e0')}),
 ('teal-harbor', 'Teal Harbor', '122c2b', 'dff2ed', '6ed2bd', {
  'surface': '193332', 'surface_alt': '213b3a', 'hover': '214742', 'pressed': '295650',
  'muted': '9bb1ad', 'disabled': '687f7c', 'selection_text': '111111',
  'accent_hover': '82d8c6', 'accent_pressed': '5fb7a6', 'border': '478c80',
  'glow': '79d5c2', 'shadow': '0b1a1a', 'success': '8ad5a7', 'warning': 'e3c980', 'error': 'df98a1',
  'ansi': ('354e4c', 'df98a1', '8ad5a7', 'e3c980', '6ed2bd', 'b6a9d7', '73d5d3', 'dff2ed', '9bb1ad', 'dfa6ad', '98dab2', 'e2d091', '80d7c5', 'bdb5db', '84dad7', 'dff2ed')}),
 ('cherry-blossom', 'Cherry Blossom', '301f27', 'f8e3eb', 'ef9db9', {
  'surface': '37262e', 'surface_alt': '3f2e36', 'hover': '4f333e', 'pressed': '603e4c',
  'muted': 'b6a2aa', 'disabled': '847179', 'selection_text': '111111',
  'accent_hover': 'f1aac2', 'accent_pressed': 'd089a2', 'border': '9f687c',
  'glow': 'f0a4be', 'shadow': '1d1317', 'success': '9bcfa7', 'warning': 'f0c47f', 'error': 'f091a1',
  'ansi': ('524048', 'f091a1', '9bcfa7', 'f0c47f', 'ef9db9', 'cd9fd7', '8accd2', 'f8e3eb', 'b6a2aa', 'f19ead', 'aad2b2', 'f1c990', 'f0a8c1', 'd4aada', '9cd0d6', 'f8e3eb')}),
 ('cobalt-cloud', 'Cobalt Cloud', '1b2340', 'e7ecfb', '9aaff8', {
  'surface': '222a47', 'surface_alt': '2a324e', 'hover': '2f395d', 'pressed': '3b466e',
  'muted': 'a4aabd', 'disabled': '71778f', 'selection_text': '111111',
  'accent_hover': 'a8baf9', 'accent_pressed': '8699db', 'border': '6574ab',
  'glow': 'a2b5f8', 'shadow': '101526', 'success': '90d1af', 'warning': 'e7c686', 'error': 'e593a9',
  'ansi': ('3e4560', 'e593a9', '90d1af', 'e7c686', '9aaff8', 'bea3e2', '7bcfde', 'e7ecfb', 'a4aabd', 'e5a1b6', '9ed5bb', 'e7cc99', 'a6b9f8', 'c5afe6', '8cd4e3', 'e7ecfb')}),
 ('olive-gold', 'Olive Gold', '28291d', 'eeefda', 'c9ce83', {
  'surface': '2f3024', 'surface_alt': '37382b', 'hover': '42432d', 'pressed': '505236',
  'muted': 'adae9c', 'disabled': '7b7c6c', 'selection_text': '111111',
  'accent_hover': 'd0d493', 'accent_pressed': 'afb473', 'border': '858958',
  'glow': 'cdd18c', 'shadow': '181911', 'success': '96d5a0', 'warning': 'ecc97a', 'error': 'eb979a',
  'ansi': ('4a4b3d', 'eb979a', '96d5a0', 'ecc97a', 'c9ce83', 'c7a8cd', '83d5c9', 'eeefda', 'adae9c', 'eba5a4', 'a4d9a9', 'eccf89', 'cfd391', 'cdb3cf', '94d9cc', 'eeefda')}),
 ('orchid-snow', 'Orchid Snow', '2b2239', 'f1e7fc', 'cba9f0', {
  'surface': '322940', 'surface_alt': '3a3148', 'hover': '453856', 'pressed': '534467',
  'muted': 'b0a6bc', 'disabled': '7e758b', 'selection_text': '111111',
  'accent_hover': 'd2b4f2', 'accent_pressed': 'b193d3', 'border': '8870a3',
  'glow': 'cfaff1', 'shadow': '1a1422', 'success': '96d0ae', 'warning': 'ecc585', 'error': 'eb92a8',
  'ansi': ('4d435a', 'eb92a8', '96d0ae', 'ecc585', 'cba9f0', 'c7a2e0', '84cedc', 'f1e7fc', 'b0a6bc', 'eca0b5', 'a5d4ba', 'edca98', 'd1b3f2', 'ceade4', '95d2e1', 'f1e7fc')}),
 ('graphite-mint', 'Graphite Mint', '202526', 'e4eeee', '89d1b9', {
  'surface': '272c2d', 'surface_alt': '2f3435', 'hover': '31413e', 'pressed': '3a504b',
  'muted': 'a3acac', 'disabled': '72797a', 'selection_text': '111111',
  'accent_hover': '99d6c3', 'accent_pressed': '78b5a1', 'border': '5d897b',
  'glow': '92d4be', 'shadow': '131617', 'success': '8dd5a7', 'warning': 'e6c97f', 'error': 'e398a1',
  'ansi': ('414748', 'e398a1', '8dd5a7', 'e6c97f', '89d1b9', 'bba9d7', '78d5d2', 'e4eeee', 'a3acac', 'e3a6ad', '9bd9b2', 'e6cf91', '98d6c1', 'c2b4db', '89d9d6', 'e4eeee')}),
 ('sandstone-sky', 'Sandstone Sky', '292827', 'f0ece5', '90bfdd', {
  'surface': '302f2e', 'surface_alt': '383735', 'hover': '394044', 'pressed': '434e54',
  'muted': 'aeaba6', 'disabled': '7d7a77', 'selection_text': '111111',
  'accent_hover': 'a1c7de', 'accent_pressed': '80a7c0', 'border': '658091',
  'glow': '9ac4de', 'shadow': '191817', 'success': '8ed3ab', 'warning': 'e6c783', 'error': 'e495a5',
  'ansi': ('4b4947', 'e495a5', '8ed3ab', 'e6c783', '90bfdd', 'bca6dd', '79d2d9', 'f0ece5', 'aeaba6', 'e6a3af', '9ed7b4', 'e8cd93', '9fc6de', 'c4b1de', '8cd6db', 'f0ece5')}),
 ('ember-night', 'Ember Night', '2c2020', 'f5e7e3', 'efad91', {
  'surface': '332727', 'surface_alt': '3b2f2f', 'hover': '4b3732', 'pressed': '5d433c',
  'muted': 'b3a5a3', 'disabled': '807472', 'selection_text': '111111',
  'accent_hover': 'f0b7a0', 'accent_pressed': 'd0967f', 'border': '9d7262',
  'glow': 'f0b399', 'shadow': '1a1313', 'success': '9bd1a2', 'warning': 'f0c57b', 'error': 'f0939b',
  'ansi': ('4e4241', 'f0939b', '9bd1a2', 'f0c57b', 'efad91', 'cda2cf', '8acfcb', 'f5e7e3', 'b3a5a3', 'f1a0a7', 'a9d5ac', 'f1ca8c', 'f0b69e', 'd3add2', '9bd3cf', 'f5e7e3')}),
 ('inkstone', 'Inkstone', '101820', 'e8f0f4', '5bd6c5', {
  'surface': '182027', 'surface_alt': '202830', 'hover': '1c363a', 'pressed': '234849',
  'muted': 'a1a9ae', 'disabled': '6b7379', 'selection_text': '111111',
  'accent_hover': '74dbcd', 'accent_pressed': '4fb8ab', 'border': '3b8680',
  'glow': '69d9ca', 'shadow': '0a0e13', 'success': '87d6a8', 'warning': 'e1c981', 'error': 'dd98a2',
  'ansi': ('353d44', 'dd98a2', '87d6a8', 'e1c981', '5bd6c5', 'b3aad9', '70d6d5', 'e8f0f4', 'a1a9ae', 'dfa6af', '97dab4', 'e2cf93', '72dacd', 'bbb5dd', '83dada', 'e8f0f4')}),
 ('sapphire-night', 'Sapphire Night', '0d1b2a', 'e7f1ff', '4ea1ff', {
  'surface': '152231', 'surface_alt': '1d2b3a', 'hover': '17304c', 'pressed': '1d3c5f',
  'muted': '9faab9', 'disabled': '697583', 'selection_text': '111111',
  'accent_hover': '6aafff', 'accent_pressed': '448cdd', 'border': '3369a6',
  'glow': '5da9ff', 'shadow': '081019', 'success': '86cfb0', 'warning': 'e0c486', 'error': 'db91aa',
  'ansi': ('323f4e', 'db91aa', '86cfb0', 'e0c486', '4ea1ff', 'b0a0e3', '6dccdf', 'e7f1ff', '9faab9', 'dda0b8', '96d4bd', 'e1cb99', '66aeff', 'b9ade7', '81d2e4', 'e7f1ff')}),
 ('aurora-violet', 'Aurora Violet', '1d1830', 'f0eaff', 'c7a0ff', {
  'surface': '241f37', 'surface_alt': '2d2840', 'hover': '382e51', 'pressed': '483a64',
  'muted': 'aaa5bb', 'disabled': '767087', 'selection_text': '111111',
  'accent_hover': 'ceadff', 'accent_pressed': 'ac8ade', 'border': '8067a8',
  'glow': 'cba7ff', 'shadow': '110e1d', 'success': '95cfb0', 'warning': 'ecc486', 'error': 'eb91aa',
  'ansi': ('413c53', 'eb91aa', '95cfb0', 'ecc486', 'c7a0ff', 'c6a0e3', '83ccdf', 'f0eaff', 'aaa5bb', 'ec9fb8', 'a4d3bd', 'edca99', 'ceacff', 'cdace7', '94d1e4', 'f0eaff')}),
 ('crimson-carbon', 'Crimson Carbon', '241416', 'f7e7ea', 'ff6f91', {
  'surface': '2b1b1d', 'surface_alt': '342426', 'hover': '47232a', 'pressed': '5b2b35',
  'muted': 'b1a1a4', 'disabled': '7d6d6f', 'selection_text': '111111',
  'accent_hover': 'fe85a1', 'accent_pressed': 'dc607d', 'border': 'a3495d',
  'glow': 'fe7b9a', 'shadow': '160c0d', 'success': '9dc9a2', 'warning': 'f2bf7b', 'error': 'f28b9b',
  'ansi': ('48383a', 'f28b9b', '9dc9a2', 'f2bf7b', 'ff6f91', 'd097cf', '8dc3cb', 'f7e7ea', 'b1a1a4', 'f39aa8', 'abceae', 'f3c58d', 'fe829f', 'd6a4d3', '9ec9d0', 'f7e7ea')}),
 ('eucalyptus', 'Eucalyptus', '11251d', 'e4f4eb', '5ee0a0', {
  'surface': '182c24', 'surface_alt': '21352c', 'hover': '1d4332', 'pressed': '24543e',
  'muted': '9eb0a7', 'disabled': '6a7c74', 'selection_text': '111111',
  'accent_hover': '76e4ae', 'accent_pressed': '52c28b', 'border': '3e9169',
  'glow': '6be2a8', 'shadow': '0a1611', 'success': '88d7a3', 'warning': 'e1ca7d', 'error': 'dd9a9d',
  'ansi': ('354840', 'dd9a9d', '88d7a3', 'e1ca7d', '5ee0a0', 'b3acd2', '70d8ce', 'e4f4eb', '9eb0a7', 'dea8a9', '97dcaf', 'e1d18f', '73e3ac', 'bbb8d6', '83dcd3', 'e4f4eb')}),
 ('desert-dawn', 'Desert Dawn', '352116', 'f9ebdb', 'ffb45d', {
  'surface': '3c281d', 'surface_alt': '443025', 'hover': '553921', 'pressed': '684628',
  'muted': 'b8a89a', 'disabled': '877669', 'selection_text': '111111',
  'accent_hover': 'febe74', 'accent_pressed': 'df9c52', 'border': 'aa763f',
  'glow': 'feba6a', 'shadow': '20140d', 'success': '9dd29b', 'warning': 'f2c676', 'error': 'f29495',
  'ansi': ('564337', 'f29495', '9dd29b', 'f2c676', 'ffb45d', 'd0a4c6', '8dd0c2', 'f9ebdb', 'b8a89a', 'f3a2a0', 'acd6a5', 'f3cc86', 'febd71', 'd7afc9', '9ed4c6', 'f9ebdb')}),
 ('deep-space', 'Deep Space', '131b2b', 'e5edff', '8f9dff', {
  'surface': '1a2232', 'surface_alt': '232b3b', 'hover': '27304d', 'pressed': '323c60',
  'muted': 'a0a8b9', 'disabled': '6b7384', 'selection_text': '111111',
  'accent_hover': '9eabff', 'accent_pressed': '7b88dd', 'border': '5b66a6',
  'glow': '98a5ff', 'shadow': '0b101a', 'success': '8ecfb0', 'warning': 'e6c486', 'error': 'e391aa',
  'ansi': ('373f4f', 'e391aa', '8ecfb0', 'e6c486', '8f9dff', 'bc9fe3', '79ccdf', 'e5edff', 'a0a8b9', 'e3a0b8', '9cd4bd', 'e6cb99', '9daaff', 'c3abe7', '8ad1e4', 'e5edff')}),
 ('rosewood', 'Rosewood', '2c1720', 'f6e7ec', 'f58bb0', {
  'surface': '331e27', 'surface_alt': '3b272f', 'hover': '4c2a37', 'pressed': '5e3444',
  'muted': 'b3a2a9', 'disabled': '816e76', 'selection_text': '111111',
  'accent_hover': 'f59cbb', 'accent_pressed': 'd57899', 'border': 'a15a74',
  'glow': 'f594b6', 'shadow': '1a0e13', 'success': '9bcca6', 'warning': 'f0c27e', 'error': 'f18e9f',
  'ansi': ('4e3a43', 'f18e9f', '9bcca6', 'f0c27e', 'f58bb0', 'ce9cd5', '8bc9d1', 'f6e7ec', 'b3a2a9', 'f29cab', 'aad0b1', 'f1c890', 'f59aba', 'd4a8d9', '9cced5', 'f6e7ec')}),
 ('petrol', 'Petrol', '0f292f', 'e2f2f3', '4fd1d9', {
  'surface': '163036', 'surface_alt': '1f383e', 'hover': '19444a', 'pressed': '1f535a',
  'muted': '9cb0b2', 'disabled': '687d81', 'selection_text': '111111',
  'accent_hover': '69d7de', 'accent_pressed': '45b6be', 'border': '348a92',
  'glow': '5ed4dc', 'shadow': '09191c', 'success': '86d5ab', 'warning': 'e0c983', 'error': 'db98a5',
  'ansi': ('334b50', 'db98a5', '86d5ab', 'e0c983', '4fd1d9', 'b1a9dc', '6dd5d8', 'e2f2f3', '9cb0b2', 'dca6b1', '95dab7', 'e0d095', '67d6dd', 'b9b5e0', '80dadc', 'e2f2f3')}),
 ('moss', 'Moss', '1c2719', 'eaf2e2', 'b7d66b', {
  'surface': '232e20', 'surface_alt': '2b3628', 'hover': '354326', 'pressed': '43532e',
  'muted': 'a6afa0', 'disabled': '737c6d', 'selection_text': '111111',
  'accent_hover': 'c0db80', 'accent_pressed': '9eba5e', 'border': '768c49',
  'glow': 'bcd977', 'shadow': '11170f', 'success': '93d69d', 'warning': 'eac978', 'error': 'e99896',
  'ansi': ('3f4a3b', 'e99896', '93d69d', 'eac978', 'b7d66b', 'c3aac8', '80d6c4', 'eaf2e2', 'a6afa0', 'e9a6a2', 'a1daa8', 'ead089', 'bfda7e', 'c9b6cc', '91dac9', 'eaf2e2')}),
 ('storm', 'Storm', '20242b', 'eef1f4', '89b7e8', {
  'surface': '272b32', 'surface_alt': '2f333a', 'hover': '313c49', 'pressed': '3a495a',
  'muted': 'aaadb2', 'disabled': '777a7f', 'selection_text': '111111',
  'accent_hover': '9bc1ea', 'accent_pressed': '789fca', 'border': '5d7999',
  'glow': '93bde9', 'shadow': '13161a', 'success': '8dd2ad', 'warning': 'e6c684', 'error': 'e394a7',
  'ansi': ('43474d', 'e394a7', '8dd2ad', 'e6c684', '89b7e8', 'bba4df', '78d0db', 'eef1f4', 'aaadb2', 'e5a3b3', '9dd7b8', 'e7cd96', '99c0ea', 'c3b0e2', '8bd5df', 'eef1f4')}),
 ('plum-gold', 'Plum Gold', '2a1b2a', 'f5e9f6', 'e0b85d', {
  'surface': '312231', 'surface_alt': '392a39', 'hover': '473432', 'pressed': '584237',
  'muted': 'b2a5b3', 'disabled': '7f7280', 'selection_text': '111111',
  'accent_hover': 'e4c179', 'accent_pressed': 'c39f55', 'border': '947648',
  'glow': 'e2bd6c', 'shadow': '191019', 'success': '99d29b', 'warning': 'eec676', 'error': 'ee9495',
  'ansi': ('4d3e4d', 'ee9495', '99d29b', 'eec676', 'e0b85d', 'cba4c6', '87d1c2', 'f5e9f6', 'b2a5b3', 'efa2a5', 'a8d6aa', 'efcc8a', 'e3c075', 'd2afce', '99d5ca', 'f5e9f6')}),
 ('electric-iris', 'Electric Iris', '171528', 'eeebff', 'c4a7ff', {
  'surface': '1f1c30', 'surface_alt': '272538', 'hover': '332c4a', 'pressed': '423a5e',
  'muted': 'a7a4b8', 'disabled': '716f82', 'selection_text': '111111',
  'accent_hover': 'ccb3ff', 'accent_pressed': 'a890dd', 'border': '7b6aa5',
  'glow': 'c8aeff', 'shadow': '0e0d18', 'success': '95d0b0', 'warning': 'ecc586', 'error': 'ea92aa',
  'ansi': ('3c394d', 'ea92aa', '95d0b0', 'ecc586', 'c4a7ff', 'c6a1e3', '82cedf', 'eeebff', 'a7a4b8', 'eba0b8', 'a3d4bd', 'eccb99', 'cbb2ff', 'ccade7', '93d3e4', 'eeebff')}),
 ('arctic-cyan', 'Arctic Cyan', '101e28', 'e5f5fa', '67e8f9', {
  'surface': '17262f', 'surface_alt': '202e38', 'hover': '1e3e49', 'pressed': '26505c',
  'muted': '9faeb5', 'disabled': '697880', 'selection_text': '111111',
  'accent_hover': '7eeaf9', 'accent_pressed': '59c8d8', 'border': '4293a1',
  'glow': '74e9f9', 'shadow': '0a1218', 'success': '89d8af', 'warning': 'e2cb86', 'error': 'de9ba9',
  'ansi': ('34434c', 'de9ba9', '89d8af', 'e2cb86', '67e8f9', 'b5ade2', '72d9de', 'e5f5fa', '9faeb5', 'dfa9b6', '98ddbb', 'e2d299', '7beaf9', 'bdb9e6', '84dde2', 'e5f5fa')}),
 ('citrus-graphite', 'Citrus Graphite', '20231a', 'f1f4e5', 'd9f070', {
  'surface': '272a21', 'surface_alt': '303329', 'hover': '3e4428', 'pressed': '4e5630',
  'muted': 'acafa2', 'disabled': '787b6f', 'selection_text': '111111',
  'accent_hover': 'ddf185', 'accent_pressed': 'bbcf62', 'border': '8b9a4c',
  'glow': 'dbf07c', 'shadow': '131510', 'success': '98d99d', 'warning': 'eecc78', 'error': 'ed9c97',
  'ansi': ('44473d', 'ed9c97', '98d99d', 'eecc78', 'd9f070', 'c9aec9', '86dbc5', 'f1f4e5', 'acafa2', 'eeaaa3', 'a6dda9', 'eed289', 'ddf183', 'cfb9cd', '97dfca', 'f1f4e5')}),
 ('coral-basalt', 'Coral Basalt', '261c1f', 'f9e9e8', 'ff9d91', {
  'surface': '2d2326', 'surface_alt': '362b2e', 'hover': '493131', 'pressed': '5c3c3c',
  'muted': 'b3a5a6', 'disabled': '7f7273', 'selection_text': '111111',
  'accent_hover': 'feaba1', 'accent_pressed': 'dc887f', 'border': 'a46761',
  'glow': 'fea59a', 'shadow': '171113', 'success': '9dcfa2', 'warning': 'f2c47b', 'error': 'f2919b',
  'ansi': ('4a3f41', 'f2919b', '9dcfa2', 'f2c47b', 'ff9d91', 'd09fcf', '8dcccb', 'f9e9e8', 'b3a5a6', 'f39fa7', 'acd3ad', 'f3ca8c', 'fea99f', 'd7abd3', '9ed1d0', 'f9e9e8')}),
 ('jade-obsidian', 'Jade Obsidian', '10221e', 'e4f6ed', '6ee7b7', {
  'surface': '172925', 'surface_alt': '20322e', 'hover': '1f4236', 'pressed': '285344',
  'muted': '9eb0a9', 'disabled': '697b75', 'selection_text': '111111',
  'accent_hover': '83eac1', 'accent_pressed': '5fc79f', 'border': '479477',
  'glow': '7ae8bc', 'shadow': '0a1412', 'success': '8ad8a6', 'warning': 'e3cb7f', 'error': 'df9aa0',
  'ansi': ('344641', 'df9aa0', '8ad8a6', 'e3cb7f', '6ee7b7', 'b6add6', '73d9d2', 'e4f6ed', '9eb0a9', 'e0a9ac', '98ddb1', 'e3d291', '81e9c0', 'bdb9da', '85ded6', 'e4f6ed')}),
 ('royal-ink', 'Royal Ink', '181b31', 'eceeff', 'a5b4fc', {
  'surface': '1f2238', 'surface_alt': '282b40', 'hover': '2f3351', 'pressed': '3b4164',
  'muted': 'a6a8bb', 'disabled': '717488', 'selection_text': '111111',
  'accent_hover': 'b2befd', 'accent_pressed': '8e9cdc', 'border': '6a74a7',
  'glow': 'acbafc', 'shadow': '0e101d', 'success': '91d2af', 'warning': 'e8c686', 'error': 'e694a9',
  'ansi': ('3c3f54', 'e694a9', '91d2af', 'e8c686', 'a5b4fc', 'c0a4e3', '7dd0de', 'eceeff', 'a6a8bb', 'e7a2b7', 'a0d6bc', 'e9cc99', 'b0bdfc', 'c7b0e7', '8fd5e3', 'eceeff')}),
 ('fuchsia-smoke', 'Fuchsia Smoke', '281a2a', 'f9eafa', 'f0abfc', {
  'surface': '2f2131', 'surface_alt': '382a3a', 'hover': '48314c', 'pressed': '5a3e5e',
  'muted': 'b4a5b5', 'disabled': '807181', 'selection_text': '111111',
  'accent_hover': 'f2b6fc', 'accent_pressed': 'd094da', 'border': '9c6ea4',
  'glow': 'f1b1fc', 'shadow': '181019', 'success': '9bd0af', 'warning': 'f0c586', 'error': 'f093a9',
  'ansi': ('4c3d4d', 'f093a9', '9bd0af', 'f0c586', 'f0abfc', 'cea2e3', '8acede', 'f9eafa', 'b4a5b5', 'f1a1b6', 'aad4bb', 'f1cb99', 'f1b5fc', 'd5aee7', '9cd2e2', 'f9eafa')}),
 ('honey-carbon', 'Honey Carbon', '282219', 'f9f0db', 'fcd34d', {
  'surface': '2f2920', 'surface_alt': '383128', 'hover': '4a3e21', 'pressed': '5d4e26',
  'muted': 'b4ac9b', 'disabled': '80796a', 'selection_text': '111111',
  'accent_hover': 'fbd867', 'accent_pressed': 'dab745', 'border': 'a38937',
  'glow': 'fcd65b', 'shadow': '18140f', 'success': '9cd699', 'warning': 'f1c975', 'error': 'f29893',
  'ansi': ('4c453a', 'f29893', '9cd699', 'f1c975', 'fcd34d', 'd0a9c3', '8cd5bf', 'f9f0db', 'b4ac9b', 'f3a69f', 'abdaa4', 'f2cf85', 'fcd864', 'd7b4c7', '9dd9c3', 'f9f0db')}),
 ('azure-steel', 'Azure Steel', '152331', 'e7f1fc', '7dd3fc', {
  'surface': '1c2a38', 'surface_alt': '253240', 'hover': '263f51', 'pressed': '2f4f64',
  'muted': 'a2adb9', 'disabled': '6d7a86', 'selection_text': '111111',
  'accent_hover': '90d8fc', 'accent_pressed': '6cb7dc', 'border': '5189a7',
  'glow': '88d6fc', 'shadow': '0d151d', 'success': '8cd6af', 'warning': 'e4c986', 'error': 'e198a9',
  'ansi': ('394654', 'e198a9', '8cd6af', 'e4c986', '7dd3fc', 'b9a9e3', '76d5de', 'e7f1fc', 'a2adb9', 'e2a6b6', '9bdabb', 'e4cf99', '8ed8fc', 'c0b5e7', '88d9e3', 'e7f1fc')}),
 ('silver-pine', 'Silver Pine', '1a2424', 'edf4f1', 'b9e4d0', {
  'surface': '212b2b', 'surface_alt': '2a3433', 'hover': '334340', 'pressed': '42544f',
  'muted': 'a7afad', 'disabled': '737b7a', 'selection_text': '111111',
  'accent_hover': 'c2e7d6', 'accent_pressed': 'a0c5b4', 'border': '769388',
  'glow': 'bee6d3', 'shadow': '101616', 'success': '94d8aa', 'warning': 'eacb82', 'error': 'e99aa4',
  'ansi': ('3e4747', 'e99aa4', '94d8aa', 'eacb82', 'b9e4d0', 'c4acdb', '80d9d7', 'edf4f1', 'a7afad', 'eaa8b0', 'a2dcb5', 'ead294', 'c1e7d5', 'cbb8df', '91dddb', 'edf4f1')}),
)
LABELS = {row[0]: row[1] for row in CATALOG}
DEFAULT_PROFILE = CATALOG[0][0]
COMPONENTS = {'fuzzel': 'Fuzzel Profiles', 'waybar': 'Waybar Profiles',
              'dock': 'Crystal-Dock Profiles', 'greeter': 'GTKGREET Profiles',
              'terminal': 'Terminal Profiles'}


def rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip('#')
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def mix(first: str, second: str, fraction: float) -> str:
    return '#' + ''.join(f'{round(a * (1 - fraction) + b * fraction):02x}'
                         for a, b in zip(rgb(first), rgb(second)))


def luminance(color: str) -> float:
    values = [c / 255 for c in rgb(color)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a: str, b: str) -> float:
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


@dataclass(frozen=True)
class Palette:
    background: str
    foreground: str
    accent: str
    surface: str
    muted: str
    border: str
    selection_text: str
    ansi: tuple[str, ...]
    surface_alt: str
    hover: str
    pressed: str
    disabled: str
    accent_hover: str
    accent_pressed: str
    glow: str
    shadow: str
    success: str
    warning: str
    error: str


def palette(identity: str, mode: str = 'dark') -> Palette:
    if identity not in LABELS or mode not in ('dark', 'light'):
        raise ValueError('unknown appearance profile or mode')
    row = next(row for row in CATALOG if row[0] == identity)
    # Older callers pass the application color mode. Every component profile
    # retains its own complete dark palette regardless of that application mode.
    bg, fg, accent = ['#' + value for value in row[2:5]]
    roles = {key: tuple('#' + c for c in value) if key == 'ansi' else '#' + value
             for key, value in row[5].items()}
    return Palette(background=bg, foreground=fg, accent=accent, **roles)


def readable_text(background: str) -> str:
    return max(('#111111', '#ffffff'), key=lambda color: contrast(background, color))


def native_palette(bg: str, fg: str, accent: str, *, dark: bool) -> Palette:
    """Build coordinated roles for an application theme or dark component."""
    surface = mix(bg, fg, 0.065)
    muted = mix(bg, fg, 0.67)
    border = mix(bg, accent, 0.48)
    selection = readable_text(accent)
    base = (('e58c8c', '92c995', 'dbbd7e', '91b9e9', 'c7a0dd', '7fcaca') if dark
            else ('a43745', '376d3f', '80600c', '2e62a2', '8046a0', '196b70'))
    normal = [mix(bg, fg, 0.18), *('#' + value for value in base), fg]
    # Accent coordinates the blue ANSI slot without sacrificing readable text.
    normal[4] = accent
    bright = [muted, *(mix(c, fg, 0.14) for c in normal[1:7]), fg]
    return Palette(background=bg, foreground=fg, accent=accent, surface=surface,
                   muted=muted, border=border, selection_text=selection,
                   ansi=tuple(normal + bright), surface_alt=mix(bg, fg, 0.10),
                   hover=mix(bg, accent, 0.16), pressed=mix(bg, accent, 0.25),
                   disabled=mix(bg, fg, 0.42), accent_hover=mix(accent, fg, 0.18),
                   accent_pressed=mix(accent, bg, 0.16), glow=mix(accent, fg, 0.10),
                   shadow=mix(bg, '#000000', 0.40), success=normal[2],
                   warning=normal[3], error=normal[1])
