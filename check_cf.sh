#!/bin/bash
NS=$1; D=socneurociencia.cl
for h in "" www mail; do echo "== A ${h:+$h.}$D"; dig +short @$NS A ${h:+$h.}$D; done
echo "== MX";    dig +short @$NS MX $D
echo "== TXT";   dig +short @$NS TXT $D
echo "== DKIM";  dig +short @$NS TXT default._domainkey.$D
echo "== DMARC"; dig +short @$NS TXT _dmarc.$D
