D=socneurociencia.cl
{
echo "== NS";   dig +short NS $D
echo "== A";    dig +short A $D
echo "== WWW";  dig +short www.$D
echo "== MX";   dig +short MX $D
echo "== TXT";  dig +short TXT $D
echo "== DS (DNSSEC)"; dig +short DS $D
for s in mail webmail smtp imap pop autodiscover ftp cpanel congreso abstracts resumenes reunion socios; do
  r=$(dig +short $s.$D); [ -n "$r" ] && echo "$s -> $r"
done
} | tee ~/scn_dns_snapshot_$(date +%F).txt
