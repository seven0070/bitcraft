/* Hand-rolled SHA256 midstate miner — Step 2 of the plan, tested.
 * First 64-byte header block is compressed ONCE per template,
 * saved as midstate. Per nonce only:
 *   compress block 2 of SHA1 (from midstate) + compress block of SHA2
 * = 2 compressions instead of 3, ~33% less compression work.
 * No OpenSSL, no SHA-NI intrinsics here — pure portable C, so the
 * benchmark is honest about software SHA256 speed.
 * Usage: same args as c_miner, plus optional nonce_end.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>

static const uint32_t K[64] = {
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
static const uint32_t H0[8] = {
0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
#define ROTR(x,n) (((x)>>(n)) | ((x)<<(32-(n))))
static void compress(uint32_t state[8], const unsigned char block[64]) {
    uint32_t w[64];
    for (int i=0;i<16;i++) w[i]=((uint32_t)block[i*4]<<24)|((uint32_t)block[i*4+1]<<16)|((uint32_t)block[i*4+2]<<8)|block[i*4+3];
    for (int i=16;i<64;i++) {
        uint32_t s0=ROTR(w[i-15],7)^ROTR(w[i-15],18)^(w[i-15]>>3);
        uint32_t s1=ROTR(w[i-2],17)^ROTR(w[i-2],19)^(w[i-2]>>10);
        w[i]=w[i-16]+s0+w[i-7]+s1;
    }
    uint32_t a=state[0],b=state[1],c=state[2],d=state[3],e=state[4],f=state[5],g=state[6],h=state[7];
    for (int i=0;i<64;i++) {
        uint32_t S1=ROTR(e,6)^ROTR(e,11)^ROTR(e,25);
        uint32_t ch=(e&f)^((~e)&g);
        uint32_t t1=h+S1+ch+K[i]+w[i];
        uint32_t S0=ROTR(a,2)^ROTR(a,13)^ROTR(a,22);
        uint32_t maj=(a&b)^(a&c)^(b&c);
        uint32_t t2=S0+maj;
        h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    state[0]+=a;state[1]+=b;state[2]+=c;state[3]+=d;state[4]+=e;state[5]+=f;state[6]+=g;state[7]+=h;
}
static int hexval(int c){ if(c>='0'&&c<='9')return c-'0'; if(c>='a'&&c<='f')return c-'a'+10; if(c>='A'&&c<='F')return c-'A'+10; return -1; }
static int hex_to_bytes(const char *hex, unsigned char *out, size_t n){ for(size_t i=0;i<n;i++){int hi=hexval((unsigned char)hex[2*i]);int lo=hexval((unsigned char)hex[2*i+1]); if(hi<0||lo<0)return -1; out[i]=(hi<<4)|lo;} return 0; }
int main(int argc, char **argv){
    if(argc<8){fprintf(stderr,"usage: version prev merkle ts bits target seconds [start] [end]\n");return 2;}
    uint32_t version=strtoul(argv[1],NULL,0);
    unsigned char prev[32],merk[32],target[32];
    if(hex_to_bytes(argv[2],prev,32)||hex_to_bytes(argv[3],merk,32)||hex_to_bytes(argv[6],target,32)){fprintf(stderr,"bad hex\n");return 2;}
    uint32_t ts=strtoul(argv[4],NULL,0), bits=strtoul(argv[5],NULL,0);
    double seconds=atof(argv[7]);
    uint64_t start=(argc>8)?strtoull(argv[8],NULL,0):0;
    uint64_t end=(argc>9)?strtoull(argv[9],NULL,0):0xffffffffULL;
    /* reverse prev/merkle for header LE */
    for(int i=0;i<16;i++){unsigned char t=prev[i];prev[i]=prev[31-i];prev[31-i]=t; t=merk[i];merk[i]=merk[31-i];merk[31-i]=t;}
    unsigned char hdr[80];
    hdr[0]=version&0xff;hdr[1]=(version>>8)&0xff;hdr[2]=(version>>16)&0xff;hdr[3]=(version>>24)&0xff;
    memcpy(hdr+4,prev,32); memcpy(hdr+36,merk,32);
    hdr[68]=ts&0xff;hdr[69]=(ts>>8)&0xff;hdr[70]=(ts>>16)&0xff;hdr[71]=(ts>>24)&0xff;
    hdr[72]=bits&0xff;hdr[73]=(bits>>8)&0xff;hdr[74]=(bits>>16)&0xff;hdr[75]=(bits>>24)&0xff;
    /* midstate: compress block 1 */
    uint32_t mid[8]; memcpy(mid,H0,sizeof(mid)); compress(mid, hdr);
    unsigned char best_rev[32]; uint64_t best_nonce=0; int have=0; uint64_t count=0;
    struct timespec t0,tn; clock_gettime(CLOCK_MONOTONIC,&t0);
    for(uint64_t nonce=start;;nonce++){
        unsigned char blk2[64]; memset(blk2,0,64);
        memcpy(blk2, hdr+64, 16); /* merk last 4 + ts + bits + nonce placeholder, nonce filled below */
        blk2[12]=nonce&0xff;blk2[13]=(nonce>>8)&0xff;blk2[14]=(nonce>>16)&0xff;blk2[15]=(nonce>>24)&0xff;
        /* Actually blk2 layout: bytes 0-3 merk[28..31], 4-7 ts, 8-11 bits, 12-15 nonce, 16=0x80, rest 0, last 8 bytes length 640 BE */
        blk2[16]=0x80; blk2[62]=0x02; blk2[63]=0x80; /* 640 = 0x0280 */
        uint32_t st[8]; memcpy(st,mid,sizeof(st)); compress(st, blk2);
        unsigned char dig1[32];
        for(int i=0;i<8;i++){dig1[i*4]=(st[i]>>24)&0xff;dig1[i*4+1]=(st[i]>>16)&0xff;dig1[i*4+2]=(st[i]>>8)&0xff;dig1[i*4+3]=st[i]&0xff;}
        unsigned char blk3[64]; memset(blk3,0,64); memcpy(blk3,dig1,32); blk3[32]=0x80; blk3[62]=0x01; blk3[63]=0x00; /* 256 */
        uint32_t st2[8]; memcpy(st2,H0,sizeof(st2)); compress(st2, blk3);
        unsigned char dig2[32], rev[32];
        for(int i=0;i<8;i++){dig2[i*4]=(st2[i]>>24)&0xff;dig2[i*4+1]=(st2[i]>>16)&0xff;dig2[i*4+2]=(st2[i]>>8)&0xff;dig2[i*4+3]=st2[i]&0xff;}
        for(int i=0;i<32;i++) rev[i]=dig2[31-i];
        count++;
        if(!have || memcmp(rev,best_rev,32)<0){memcpy(best_rev,rev,32);best_nonce=nonce;have=1;}
        /* target check */
        int lt=0, gt=0; for(int i=0;i<32;i++){if(rev[i]<target[i]){lt=1;break;} if(rev[i]>target[i]){gt=1;break;}}
        if(lt){char hex[65]; for(int i=0;i<32;i++) sprintf(hex+2*i,"%02x",rev[i]); hex[64]=0; printf("VALID_FOUND nonce=%llu hash=%s\n",(unsigned long long)nonce,hex); return 10;}
        if(nonce>=end) break;
        if((count & 0x7ffff)==0){clock_gettime(CLOCK_MONOTONIC,&tn); double el=(tn.tv_sec-t0.tv_sec)+(tn.tv_nsec-t0.tv_nsec)/1e9; if(el>=seconds) break;}
    }
    clock_gettime(CLOCK_MONOTONIC,&tn); double el=(tn.tv_sec-t0.tv_sec)+(tn.tv_nsec-t0.tv_nsec)/1e9;
    char hex[65]; for(int i=0;i<32;i++) sprintf(hex+2*i,"%02x",best_rev[i]); hex[64]=0;
    printf("hashed %llu in %.1f s = %.0f H/s\n",(unsigned long long)count,el,count/(el>0?el:1));
    printf("best nonce %llu\n",(unsigned long long)best_nonce);
    printf("best hash %s\n",hex);
    return 0;
}
