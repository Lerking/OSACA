#!/usr/bin/env python3

import pyparsing as pp

from .base_parser import BaseParser


class ParserX86ATT(BaseParser):
    def __init__(self):
        super().__init__()

    def construct_parser(self):
        # Comment
        symbol_comment = '#'
        self.comment = pp.Literal(symbol_comment) + pp.Group(
            pp.ZeroOrMore(pp.Word(pp.printables))
        ).setResultsName(self.COMMENT_ID)
        # Define x86 assembly identifier
        first = pp.Word(pp.alphas + '_.', exact=1)
        rest = pp.Word(pp.alphanums + '_.')
        identifier = pp.Combine(first + pp.Optional(rest))
        # Label
        self.label = pp.Group(
            identifier.setResultsName('name') + pp.Literal(':') + pp.Optional(self.comment)
        ).setResultsName(self.LABEL_ID)
        # Directive
        commaSeparatedList = pp.delimitedList(pp.Optional(pp.quotedString | identifier), delim=',')
        self.directive = pp.Group(
            pp.Literal('.')
            + pp.Word(pp.alphanums + '_').setResultsName('name')
            + commaSeparatedList.setResultsName('parameters')
            + pp.Optional(self.comment)
        ).setResultsName(self.DIRECTIVE_ID)

        ##############################
        # Instructions
        # Mnemonic
        mnemonic = pp.ZeroOrMore(pp.Literal('data16') ^ pp.Literal('data32')) + pp.Word(
            pp.alphanums
        )
        # Register: pp.Regex('^%[0-9a-zA-Z]+,?')
        register = pp.Group(
            pp.Literal('%')
            + pp.Word(pp.alphanums).setResultsName('name')
            + pp.Optional(
                pp.Literal('{')
                + pp.Literal('%')
                + pp.Word(pp.alphanums).setResultsName('mask')
                + pp.Literal('}')
            )
            + pp.Optional(pp.Suppress(pp.Literal(',')))
        ).setResultsName(self.REGISTER_ID)
        # Immediate: pp.Regex('^\$(-?[0-9]+)|(0x[0-9a-fA-F]+),?')
        symbol_immediate = '$'
        decimal_number = pp.Combine(
            pp.Optional(pp.Literal('-')) + pp.Word(pp.nums)
        ).setResultsName('value')
        hex_number = pp.Combine(pp.Literal('0x') + pp.Word(pp.hexnums)).setResultsName('value')
        immediate = pp.Group(
            pp.Literal(symbol_immediate)
            + (decimal_number ^ hex_number)
            + pp.Optional(pp.Suppress(pp.Literal(',')))
        ).setResultsName(self.IMMEDIATE_ID)
        # Memory: offset(base, index, scale)
        offset = decimal_number ^ hex_number
        scale = pp.Word('1248', exact=1)
        memory = pp.Group(
            pp.Optional(offset.setResultsName('offset'))
            + pp.Literal('(')
            + register.setResultsName('base')
            + pp.Optional(register.setResultsName('index'))
            + pp.Optional(scale.setResultsName('scale'))
            + pp.Literal(')')
            + pp.Optional(pp.Suppress(pp.Literal(',')))
            + pp.Optional(self.comment)
        ).setResultsName(self.MEMORY_ID)
        # Combine to instruction form
        operand1 = pp.Group(register ^ immediate ^ memory ^ identifier).setResultsName('operand1')
        operand2 = pp.Group(register ^ immediate ^ memory).setResultsName('operand2')
        operand3 = pp.Group(register ^ immediate ^ memory).setResultsName('operand3')
        self.instruction_parser = (
            mnemonic.setResultsName('mnemonic')
            + operand1
            + pp.Optional(operand2)
            + pp.Optional(operand3)
            + pp.Optional(self.comment)
        )

    def parse_line(self, line, line_number=None):
        """
        Parse line and return instruction form.

        :param str line: line of assembly code
        :param int line_id: default None, identifier of instruction form
        :return: parsed instruction form
        """
        instruction_form = {
            'instruction': None,
            'operands': None,
            'directive': None,
            'comment': None,
            'label': None,
            'line_number': line_number,
        }
        result = None

        # 1. Parse comment
        try:
            result = self.comment.parseString(line, parseAll=True).asDict()
            instruction_form['comment'] = ' '.join(result[self.COMMENT_ID])
        except pp.ParseException:
            pass

        # 2. Parse label
        if result is None:
            try:
                result = self.label.parseString(line, parseAll=True).asDict()
                instruction_form['label'] = result[self.LABEL_ID]['name']
                if self.COMMENT_ID in result[self.LABEL_ID]:
                    instruction_form['comment'] = ' '.join(result[self.COMMENT_ID])
            except pp.ParseException:
                pass

        # 3. Parse directive
        if result is None:
            try:
                result = self.directive.parseString(line, parseAll=True).asDict()
                instruction_form['directive']['name'] = result[self.DIRECTIVE_ID]['name']
                instruction_form['directive']['parameters'] = result[self.DIRECTIVE_ID][
                    'parameters'
                ]
                if self.COMMENT_ID in result[self.DIRECTIVE_ID]:
                    instruction_form['comment'] = ' '.join(
                        result[self.DIRECTIVE_ID][self.COMMENT_ID]
                    )
            except pp.ParseException:
                pass

        # 4. Parse instruction
        if result is None:
            result = self.parse_instruction(line)
            instruction_form['instruction'] = result['instruction']
            instruction_form['operands'] = result['operands']
            instruction_form['comment'] = result['comment']

        return instruction_form

    def parse_instruction(self, instruction):
        result = self.instruction_parser.parseString(instruction, parseAll=True).asDict()
        operands = {'sources': []}
        # Check from right to left
        # Check third operand
        if 'operand3' in result:
            operands['destination'] = result['operand3']
        # Check second operand
        if 'operand2' in result:
            if 'destination' in operands:
                operands['sources'].insert(0, result['operand2'])
            else:
                operands['destination'] = result['operand2']
        # Add first operand
        if 'destination' in operands:
            operands['sources'].insert(0, result['operand1'])
        else:
            operands['destination'] = result['operand1']
        return_dict = {
            'instruction': result['mnemonic'],
            'operands': operands,
            'comment': ' '.join(result['comment']) if 'comment' in result else None,
        }
        return return_dict

    def substitute_memory_address(self, memory_address):
        # remove unecessarily created dictionary entries
        raise NotImplementedError