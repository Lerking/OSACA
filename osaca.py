#!/apps/python/3.5-anaconda/bin/python

import argparse
import sys
import subprocess 
import os
import re
from  Params import *
from EUsched import *
import pandas as pd
from datetime import datetime
import numpy as np

#----------Global variables--------------
arch = ''
archList = ['SNB','IVB','HSW', 'BDW', 'SKL']
filepath = ''
srcCode = ''
marker = r'//STARTLOOP'
asm_line = re.compile(r'\s[0-9a-f]+[:]')
numSeps = 0
sem = 0
firstAppearance = True
instrForms = list()
df = ''
horizontalSeparator = ''
longestInstr = 30
cycList = []
reciList = []
# Matches every variation of the IACA start marker
iaca_sm = re.compile(r'\s*movl[ \t]+\$111[ \t]*,[ \t]*%ebx[ \t]*\n\s*\.byte[ \t]+100[ \t]*((,[ \t]*103[ \t]*((,[ \t]*144)|(\n\s*\.byte[ \t]+144)))|(\n\s*\.byte[ \t]+103[ \t]*((,[ \t]*144)|(\n\s*\.byte[ \t]+144))))')
# Matches every variation of the IACA end marker
iaca_em = re.compile(r'\s*movl[ \t]+\$222[ \t]*,[ \t]*%ebx[ \t]*\n\s*\.byte[ \t]+100[ \t]*((,[ \t]*103[ \t]*((,[ \t]*144)|(\n\s*\.byte[ \t]+144)))|(\n\s*\.byte[ \t]+103[ \t]*((,[ \t]*144)|(\n\s*\.byte[ \t]+144))))')
#---------------------------------------

# Check if the architecture arg is valid
def check_arch():
    if(arch in archList):
        return True
    else:
        return False

# Check if the given filepath exists and if the format is the needed elf64
def check_elffile():
    if(os.path.isfile(filepath)):
        create_elffile()
        if('file format elf64' in srcCode[1]):
            return True
    return False

# Check if the given filepath exists
def check_file(iacaFlag=False):
    if(os.path.isfile(filepath)):
        get_file(iacaFlag)
        return True
    return False

# Load binary file in variable srcCode and separate by line
def create_elffile():
    global srcCode
    srcCode = subprocess.run(['objdump', '--source', filepath], stdout=subprocess.PIPE).stdout.decode('utf-8').split('\n')

# Load arbitrary file in variable srcCode and separate by line
def get_file(iacaFlag):
    global srcCode
    srcCode = ''
    try:
        f = open(filepath, 'r')
    except IOError:
        print('IOError: file \'{}\' not found'.format(filepath))
    for line in f:
        srcCode += line
    f.close()
    if(iacaFlag):
        return
    srcCode = srcCode.split('\n')


def check_line(line):
    global numSeps
    global sem
    global firstAppearance
# Check if marker is in line
    if(marker in line):
# First, check if high level code in indented with whitespaces or tabs
        if(firstAppearance):
            set_char_counter(line)
            firstAppearance = False
# Now count the number of whitespaces
        numSeps = (re.split(marker, line)[0]).count(cntChar)
        sem = 2
    elif(sem > 0):
# We're in the marked code snippet
# Check if the line is ASM code and - if not - check if we're still in the loop
        match = re.search(asm_line, line)
        if(match):
# Further analysis of instructions
# Check if there are comments in line
            if(r'//' in line):
                return
            check_instr(''.join(re.split(r'\t', line)[-1:]))
        elif((re.split(r'\S', line)[0]).count(cntChar) <= numSeps):
# Not in the loop anymore - or yet. We decrement the semaphore
            sem = sem-1
    

# Check if separators are either tabulators or whitespaces
def set_char_counter(line):
    global cntChar
    numSpaces = (re.split(marker, line)[0]).count(' ')
    numTabs = (re.split(marker, line)[0]).count('\t')
    if(numSpaces != 0 and numTabs == 0):
        cntChar = ' '
    elif(numSpaces == 0 and numTabs != 0):
        cntChar = '\t'
    else:
        raise NotImplementedError('Indentation of code is only supported for whitespaces and tabs.')


def check_instr(instr):
    global instrForms
    global longestInstr
# Check for strange clang padding bytes
    while(instr.startswith('data32')):
        instr = instr[7:]
# Separate mnemonic and operands
    mnemonic = instr.split()[0]
    params = ''.join(instr.split()[1:])
# Check if line is not only a byte
    empty_byte = re.compile(r'[0-9a-f]{2}')
    if(re.match(empty_byte, mnemonic) and len(mnemonic) == 2):
        return
# Check if there's one or more operands and store all in a list
    param_list = flatten(separate_params(params))
    param_list_types = list(param_list)
# check operands and separate them by IMMEDIATE (IMD), REGISTER (REG). MEMORY (MEM) or LABEL(LBL)
    for i in range(len(param_list)):
        op = param_list[i]
        if(len(op) <= 0):
            op = Parameter('NONE')
        elif(op[0] == '$'):
            op = Parameter('IMD')
        elif(op[0] == '%' and '(' not in op):
            j = len(op)
            opmask = False
            if('{' in op):
                j = op.index('{')
                opmask = True
            op = Register(op[1:j], opmask)
        elif('<' in op or op.startswith('.')):
            op = Parameter('LBL')
        else:
            op = MemAddr(op)
        param_list[i] = op.print()
        param_list_types[i] = op
#Add to list
    if(len(instr) > longestInstr):
        longestInstr = len(instr)
    instrForm = [mnemonic]+list(reversed(param_list_types))+[instr]
    instrForms.append(instrForm)


# Extract instruction forms out of binary file
def iaca_bin():
    global marker
    global sem
    global instrForms

    marker = r'fs addr32 nop'
    for line in srcCode:
# Check if marker is in line
        if(marker in line):
            sem += 1
        elif(sem == 1):
# We're in the marked code snippet
# Check if the line is ASM code
            match = re.search(asm_line, line)
            if(match):
# Further analysis of instructions
# Check if there are comments in line
                if(r'//' in line):
                    continue
# Do the same instruction check as for the OSACA marker line check
                check_instr(''.join(re.split(r'\t', line)[-1:]))
        elif(sem == 2):
# Not in the loop anymore. Due to the fact it's the IACA marker we can stop here
# After removing the last line which belongs to the IACA marker
            del instrForms[-1:]
            return
            

# Extract instruction forms out of assembly file
def iaca_asm():
# Extract the code snippet surround by the IACA markers
    code = srcCode
# Search for the start marker
    match = re.match(iaca_sm, code)
    while(not match):
        code = code.split('\n',1)[1]
        match = re.match(iaca_sm, code)
# Search for the end marker
    code = (code.split('144',1)[1]).split('\n',1)[1]
    res = ''
    match = re.match(iaca_em, code)
    while(not match):
        res += code.split('\n',1)[0]+'\n'
        code = code.split('\n',1)[1]
        match = re.match(iaca_em, code)
# Split the result by line go on like with OSACA markers
    res = res.split('\n')
    for line in res:
        line = line.split('#')[0]
        line = line.lstrip()
        if(len(line) == 0 or '//' in line or line.startswith('..')):
            continue
        check_instr(line)


def separate_params(params):
    param_list = [params]
    if(',' in params):
        if(')' in params):
            if(params.index(')') < len(params)-1 and params[params.index(')')+1] == ','):
                i = params.index(')')+1
            elif(params.index('(') < params.index(',')):
                return param_list
            else:
                i = params.index(',')
        else:
            i = params.index(',')
        param_list = [params[:i],separate_params(params[i+1:])]
    elif('#' in params):
        i = params.index('#')
        param_list = [params[:i]]
    return param_list

def flatten(l):
    if l == []:
        return l
    if(isinstance(l[0], list)):
        return flatten(l[0]) + flatten(l[1:])
    return l[:1] + flatten(l[1:])

def read_csv():
    global df
    currDir = os.path.realpath(__file__)[:-8]
    df = pd.read_csv(currDir+'data/'+arch.lower()+'_data.csv')

def create_horiz_sep():
    global horizontalSeparator
    horizontalSeparator = '-'*(longestInstr+8)

def create_output(tp_list=False,pr_sched=True):
    global longestInstr
    
#Check the output alignment depending on the longest instruction
    if(longestInstr > 70):
        longestInstr = 70
    create_horiz_sep()
    ws = ' '*(len(horizontalSeparator)-23)
# Write general information about the benchmark
    output = (  '--'+horizontalSeparator+'\n'
                '| Analyzing of file:\t'+os.getcwd()+'/'+filepath+'\n'
                '| Architecture:\t\t'+arch+'\n'
                '| Timestamp:\t\t'+datetime.now().strftime('%Y-%m-%d %H:%M:%S')+'\n')

    if(tp_list):
        output += create_TP_list(instrForms)
    if(pr_sched):
        output += '\n\n'
        sched = Scheduler(arch, instrForms) 
        schedOutput,totalTP = sched.schedule_FCFS()
        output += sched.get_head()+schedOutput
        output += 'Total number of estimated throughput: '+str(totalTP)
    return output


def create_TP_list(instrForms):        
    warning = False
    ws = ' '*(len(horizontalSeparator)-23)

    output =   ('\n| INSTRUCTION'+ws+'CLOCK CYCLES\n'
                '| '+horizontalSeparator+'\n|\n')
# Check for the throughput data in CSV
# First determine if we're searching for the SSE, AVX or AVX512 type of instruction      
    for elem in instrForms:
        extension = ''
        opExt = []
        for i in range(1, len(elem)-1):
            optmp = ''
            if(isinstance(elem[i], Register) and elem[i].reg_type == 'GPR'):
                optmp = 'r'+str(elem[i].size)
            elif(isinstance(elem[i], MemAddr)):
                optmp = 'mem'
            else:
                optmp = elem[i].print().lower()
            opExt.append(optmp)
        operands = '_'.join(opExt)
# Now look up the value in the dataframe
# Check if there is a stored throughput value in database
        import warnings
        warnings.filterwarnings("ignore", 'This pattern has match groups')
        series = df['instr'].str.contains(elem[0]+'-'+operands)
        if( True in series.values):
# It's a match!
            notFound = False
            try:
                tp = df[df.instr == elem[0]+'-'+operands].TP.values[0]
            except IndexError:
# Something went wrong
                print('Error while fetching data from database')
                continue
# Did not found the exact instruction form.
# Try to find the instruction form for register operands only
        else:
            opExtRegs = []
            for operand in opExt:
                try:
                    regTmp = Register(operand)
                    opExtRegs.append(True)
                except KeyError:
                    opExtRegs.append(False)
                    pass
            if(not True in opExtRegs):
# No register in whole instruction form. How can I found out what regsize we need?
                print('Feature not included yet: ', end='')
                print(elem[0]+' for '+operands)
                tp = 0
                notFound = True
                warning = True

                numWhitespaces = longestInstr-len(elem[-1])
                ws = ' '*numWhitespaces+'|  '
                n_f = ' '*(5-len(str(tp)))+'*'
                data = '| '+elem[-1]+ws+str(tp)+n_f+'\n'
                output += data
                continue
            if(opExtRegs[0] == False):
# Instruction stores result in memory. Check for storing in register instead
                if(len(opExt) > 1):
                    if(opExtRegs[1] == True):
                        opExt[0] = opExt[1]
                    elif(len(optExt > 2)):
                        if(opExtRegs[2] == True):
                            opExt[0] = opExt[2]
            if(len(opExtRegs) == 2 and opExtRegs[1] == False):
# Instruction loads value from memory and has only two operands. Check for loading from register instead
                if(opExtRegs[0] == True):
                    opExt[1] = opExt[0]
            if(len(opExtRegs) == 3 and opExtRegs[2] == False):
# Instruction loads value from memory and has three operands. Check for loading from register instead
                opExt[2] = opExt[0]
            operands = '_'.join(opExt)
# Check for register equivalent instruction
            series = df['instr'].str.contains(elem[0]+'-'+operands)
            if( True in series.values):
# It's a match!
                notFound = False
                try:
                    tp = df[df.instr == elem[0]+'-'+operands].TP.values[0]

                except IndexError:
# Something went wrong
                    print('Error while fetching data from database')
                    continue
# Did not found the register instruction form. Set warning and go on with throughput 0
            else:
                tp = 0
                notFound = True
                warning = True
# Check the alignement again
        numWhitespaces = longestInstr-len(elem[-1])
        ws = ' '*numWhitespaces+'|  '
        n_f = ''
        if(notFound):
            n_f = ' '*(5-len(str(tp)))+'*'
        data = '| '+elem[-1]+ws+'{:3.2f}'.format(tp)+n_f+'\n'
        output += data
# Finally end the list of  throughput values
    numWhitespaces = longestInstr-27
    ws = '  '+' '*numWhitespaces
    output += '| '+horizontalSeparator+'\n'
    if(warning):
        output += ('\n\n* There was no throughput value found '
                    'for the specific instruction form.'
                    '\n  Please create a testcase via the create_testcase-method '
                    'or add a value manually.')
    return output


def create_sequences():
    global cycList
    global reciList

    for i in range(1, 101):
        cycList.append(i)
        reciList.append(1/i)

def validate_val(clkC, instr, isTP):
    clmn = 'LT'
    if(isTP):
        clmn = 'TP'
    for i in range(0, 100):
        if(cycList[i]*1.05 > float(clkC) and cycList[i]*0.95 < float(clkC)):
# Value is probably correct, so round it to the estimated value
            return cycList[i]
# Check reciprocal only if it is a throughput value
        elif(isTP and reciList[i]*1.05 > float(clkC) and reciList[i]*0.95 < float(clkC)):
# Value is probably correct, so round it to the estimated value
            return reciList[i]
# No value close to an integer or its reciprokal found, we assume the measurement is incorrect
    print('Your measurement for {} ({}) is probably wrong. Please inspect your benchmark!'.format(instr, clmn))
    print('The program will continue with the given value')
    return clkC

def write_csv(csv):
    try:
        f = open('data/'+arch.lower()+'_data.csv', 'w')
    except IOError:
        print('IOError: file \'{}\' not found in ./data'.format(arch.lower()+'_data.csv'))
    f.write(csv)
    f.close()

##---------------main functions depending on arguments----------------------

#reads ibench output and includes it in the architecture specific csv file
def include_ibench():
    global df

# Check args and exit program if something's wrong
    if(not check_arch()):
        print('Invalid microarchitecture.')
        sys.exit()
    if(not check_file()):
        print('Invalid file path or file format.')
        sys.exit()
# Check for database for the chosen architecture
    read_csv()
# Create sequence of numbers and their reciprokals for validate the measurements
    create_sequences()
    
    print('Everything seems fine! Let\'s start!')
    newData = []
    addedValues = 0
    for line in srcCode:
        if('Using frequency' in line or len(line) == 0):
            continue
        clmn = 'LT'
        instr = line.split()[0][:-1]
        if('TP' in line):
# We found a command with a throughput value. Get instruction and the number of clock cycles
# and remove the '-TP' suffix
            clmn = 'TP'
            instr = instr[:-3]
# Otherwise stay with Latency
        clkC = line.split()[1]
        clkC_tmp = clkC
        clkC = validate_val(clkC, instr, True if (clmn == 'TP') else False)
        txtOutput = True if (clkC_tmp == clkC) else False
        val = -2
        new = False
        try:
            entry = df.loc[lambda df: df.instr == instr,clmn]
            val = entry.values[0]
        except IndexError:
# Instruction not in database yet --> add it
            new = True
# First check if LT or TP value has already been added before
            for i,item in enumerate(newData):
                if(instr in item):
                    if(clmn == 'TP'):
                        newData[i][1] = clkC
                    elif(clmn == 'LT'):
                        newData[i][2] = clkC
                    new = False
                    break
            if(new and clmn == 'TP'):
                newData.append([instr,clkC,'-1'])
            elif(new and clmn == 'LT'):
                newData.append([instr,'-1',clkC])              
            new = True
            addedValues += 1
            pass
# If val is -1 (= not filled with a valid value) add it immediately
        if(val == -1):
            df.set_value(entry.index[0], clmn, clkC)
            addedValues += 1
            continue
        if(not new and abs((val/np.float64(clkC))-1) > 0.05):
            print('Different measurement for {} ({}): {}(old) vs. {}(new)\nPlease check for correctness (no changes were made).'.format(instr, clmn, val, clkC))
            txtOutput = True
        if(txtOutput):
            print()
            txtOutput = False
# Now merge the DataFrames and write new csv file
    df = df.append(pd.DataFrame(newData, columns=['instr','TP','LT']), ignore_index=True)
    csv = df.to_csv(index=False)
    write_csv(csv)
    print('ibench output {} successfully in database included.'.format(filepath.split('/')[-1]))
    print('{} values were added.'.format(addedValues))

                
# main function of the tool
def inspect_binary():
# Check args and exit program if something's wrong
    if(not check_arch()):
        print('Invalid microarchitecture.')
        sys.exit()
    if(not check_elffile()):
        print('Invalid file path or file format.')
        sys.exit()
# Finally check for database for the chosen architecture
    read_csv()

    print('Everything seems fine! Let\'s start checking!')
    for line in srcCode:
        check_line(line)
    output = create_output()
    print(output)


# main function of the tool with IACA markers instead of OSACA marker
def inspect_with_iaca():
# Check args and exit program if something's wrong
    if(not check_arch()):
        print('Invalid microarchitecture.')
        sys.exit()
# Check if input file is a binary or assembly file
    try:
        binaryFile = True
        if(not check_elffile()):
            print('Invalid file path or file format.')
            sys.exit()
    except (TypeError,IndexError):
        binaryFile = False
        if(not check_file(True)):
            print('Invalid file path or file format.')
            sys.exit()       
# Finally check for database for the chosen architecture
    read_csv()

    print('Everything seems fine! Let\'s start checking!')
    if(binaryFile):
        iaca_bin()
    else:
        iaca_asm()
    output = create_output()
    print(output)



##------------------------------------------------------------------------------
##------------Main method--------------
def main():
    global inp
    global arch
    global filepath
# Parse args
    parser = argparse.ArgumentParser(description='Analyzes a marked innermost loop snippet for a given architecture type and prints out the estimated average throughput')
    parser.add_argument('-V', '--version', action='version', version='%(prog)s 0.1')
    parser.add_argument('--arch', dest='arch', type=str, help='define architecture (SNB, IVB, HSW, BDW, SKL)')
    parser.add_argument('filepath', type=str, help='path to object (Binary, ASM, CSV)')
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('-i', '--include-ibench', dest='incl', action='store_true', help='includes the given values in form of the output of ibench in the database')
    group.add_argument('--iaca', dest='iaca', action='store_true', help='search for IACA markers instead the OSACA marker')
    group.add_argument('-m', '--insert-marker', dest='insert_marker', action='store_true', help='try to find blocks probably corresponding to loops in assembly and insert IACA marker')

# Store args in global variables
    inp = parser.parse_args()
    if(inp.arch is None and inp.insert_marker is None):
        raise ValueError('Please specify an architecture')
    if(inp.arch is not None):
        arch = inp.arch.upper()
    filepath = inp.filepath
    inclIbench = inp.incl
    iacaFlag = inp.iaca
    insert_m = inp.insert_marker
    
    if(inclIbench):
        include_ibench()
    elif(iacaFlag):
        inspect_with_iaca()
    elif(insert_m):
        try:
            from kerncrafts import iaca
        except ImportError:
           print('ImportError: Module kerncraft not installed. Use \'pip install --user kerncraft\' for installation.\nFor more information see https://github.com/RRZE-HPC/kerncraft')
           sys.exit()
        iaca.iaca_instrumentation(input_file=filepath, output_file=filepath,
                                  block_selection='manual', pointer_increment=1)
    else:
        inspect_binary()


##------------Main method--------------
if __name__ == '__main__':
    main()
