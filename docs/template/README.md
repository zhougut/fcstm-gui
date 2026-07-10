# Fsm Generation Template

Code Generation Template for The FSM C Code Generation.

A DSL code sample for the generation

```
def int a = 0;
def int b = 0x2 | 0x5;

state LX {
    [*] -> LX1;
    [*] -> LX2 :: EEE;

    enter {
        b = 0 + b;
        b = 3 + a * (2 + b);
    }

    exit {
        b = 0;
        b = a << 2;
    }

    state LX1 {
        during before abstract BeforeLX1Enter;
        during after abstract AfterLX1Enter /*
            this is the comment line
        */
        during before {
            b = 1 + 2;
        }
        during after {
            b = 3 - 2;
            b = 3 + 2 + a;
        }

        state LX11 {
            enter abstract LX11Enter;
            exit abstract LX11Exit;
            during abstract LX11During; 
            enter abstract /*
                This is X
                    this is x'
            */
            during {
                b = 0x2 << 0x3;
                b = b + -1;
            }
        }
        state LX12;
        state LX13;
        state LX14;

        [*] -> LX11;
        LX11 -> LX12 :: E1;
        LX12 -> LX13 :: E1;
        LX12 -> LX14 :: E2;

        LX13 -> [*] :: E1 effect {
            a = 0x2;
        }
        LX13 -> [*] :: E2 effect {
            a = 0x3;
        }
        LX13 -> LX14 :: E3;
        LX13 -> LX14 :: E4;
        LX14 -> LX12 :: E1;
        LX14 -> [*] :: E2 effect {
            a = 0x1;
        }
    }

    state LX2 {
        [*] -> LX21;
        state LX21 {
            state LX211;
            state LX212;
            [*] -> LX211 : if [a == 0x2];
            [*] -> LX212 : if [a == 0x3];
            LX211 -> [*] :: E1 effect {
                a = 0x1;
            }
            LX211 -> LX212 :: E2;
            LX212 -> [*] :: E1 effect {
                a = 0x1;
            }
            LX212 -> LX211 : E2;
        }
        LX21 -> [*] : if [a == 0x1];
    }

    LX1 -> LX2 : if [a == 0x2 || a == 0x3];
    LX1 -> LX1 : if [a == 0x1];
    LX2 -> LX1 : if [a == 0x1];
}
```

