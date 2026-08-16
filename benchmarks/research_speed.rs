use pdf_inspector::process_research_pdf;
use std::env;
use std::time::Instant;

const FNV_OFFSET: u64 = 0xcbf29ce484222325;
const FNV_PRIME: u64 = 0x100000001b3;

fn hash(mut h: u64, bytes: &[u8]) -> u64 {
    for &b in bytes {
        h ^= u64::from(b);
        h = h.wrapping_mul(FNV_PRIME);
    }
    h
}

fn main() {
    let paths: Vec<String> = env::args().skip(1).collect();
    assert!(!paths.is_empty(), "at least one PDF is required");
    let start = Instant::now();
    let mut digest = FNV_OFFSET;
    let mut total = 0usize;
    for path in paths {
        let out = process_research_pdf(&path).expect("parse");
        let md = out.markdown.expect("markdown");
        total += md.len();
        digest = hash(digest, md.as_bytes());
    }
    println!("{} {} {}", start.elapsed().as_nanos(), digest, total);
}
